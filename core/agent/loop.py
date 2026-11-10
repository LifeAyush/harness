"""The agent loop: model → tool calls? → tools → model → … → answer.

Rules (docs/phase1.md §3):
  1. Append the user message to the context.
  2. Call the model with the tools and the context.
  3. No tool calls: the reply is the final answer.
  4. Otherwise validate and run each call through the registry, append the
     results, and go back to 2.
  5. Always terminate: max_iterations, a wall-clock timeout and a token budget.

The loop knows nothing about specific tools or providers. Adding a tool means
registering it; adding a provider means implementing ModelProvider.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from core.agent.agent import DEFAULT_SYSTEM_PROMPT, AgentState, StopReason
from core.model.interface import Message, ModelError, ModelProvider
from core.tools.registry import ToolRegistry


@dataclass(frozen=True)
class Limits:
    max_iterations: int = 10  # model calls per run
    timeout_s: float = 120.0  # wall clock for the whole run
    max_tokens: int = 100_000  # prompt + completion tokens across the run


async def run(
    task: str,
    model: ModelProvider,
    registry: ToolRegistry,
    limits: Limits = Limits(),
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> AgentState:
    state = AgentState.start(task, system_prompt)
    try:
        await asyncio.wait_for(_loop(state, model, registry, limits), timeout=limits.timeout_s)
    except asyncio.TimeoutError:
        state.stop(StopReason.TIMEOUT, f"run exceeded {limits.timeout_s:g}s")
    return state


async def _loop(state: AgentState, model: ModelProvider, registry: ToolRegistry, limits: Limits) -> None:
    specs = registry.specs()
    while True:
        if state.iteration >= limits.max_iterations:
            state.stop(StopReason.MAX_ITERATIONS, f"no final answer after {limits.max_iterations} model calls")
            return
        if state.usage.total >= limits.max_tokens:
            state.stop(StopReason.TOKEN_BUDGET, f"used {state.usage.total} of {limits.max_tokens} tokens")
            return

        state.iteration += 1
        started = time.time()
        try:
            response = await model.complete(state.messages, specs)
        except ModelError as exc:
            state.stop(StopReason.MODEL_ERROR, str(exc))
            return
        except Exception as exc:  # a provider bug must not escape as a crash
            state.stop(StopReason.MODEL_ERROR, f"{type(exc).__name__}: {exc}")
            return

        reply = response.message
        state.usage = state.usage + response.usage
        state.messages.append(reply)
        state.record(
            "model",
            started,
            {
                "iteration": state.iteration,
                "content": reply.content,
                "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.tool_calls],
                "usage": {"prompt": response.usage.prompt_tokens, "completion": response.usage.completion_tokens},
            },
        )

        if not reply.tool_calls:
            state.answer = reply.content or ""
            state.stop(StopReason.FINAL_ANSWER)
            return

        # Sequential for now; Phase 3 moves tool execution onto workers.
        for call in reply.tool_calls:
            started = time.time()
            result = await registry.dispatch(call)
            state.messages.append(Message("tool", result.content, tool_call_id=call.id, name=call.name))
            state.record(
                "tool",
                started,
                {"call_id": call.id, "name": call.name, "arguments": call.arguments, "is_error": result.is_error, "result": result.content},
            )
