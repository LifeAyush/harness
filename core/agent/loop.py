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
import uuid
from dataclasses import dataclass

from core.agent.agent import DEFAULT_SYSTEM_PROMPT, AgentState, StopReason
from core.model.interface import Message, ModelError, ModelProvider
from core.session.events import (
    ModelCallCompleted,
    ModelCallRequested,
    SessionCompleted,
    SessionCreated,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
)
from core.session.store import EventStore, InMemoryEventStore
from core.tools.registry import ToolRegistry


class _Log:
    """Appends one run's events to the store with consecutive sequence numbers."""

    def __init__(self, store: EventStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id
        self.seq = 0

    def emit(self, cls, **fields) -> None:
        self.store.append(cls(session_id=self.session_id, sequence_number=self.seq, **fields))
        self.seq += 1


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
    store: EventStore | None = None,
    session_id: str | None = None,
) -> AgentState:
    """Run one task. Every step is appended to ``store`` (a fresh in-memory one by default)
    under ``session_id`` (a new uuid by default); ``state.session_id`` says which."""
    state = AgentState.start(task, system_prompt)
    state.session_id = session_id or uuid.uuid4().hex
    log = _Log(store if store is not None else InMemoryEventStore(), state.session_id)
    log.emit(SessionCreated, task=task, system_prompt=system_prompt)
    try:
        await asyncio.wait_for(_loop(state, model, registry, limits, log), timeout=limits.timeout_s)
    except asyncio.TimeoutError:
        state.stop(StopReason.TIMEOUT, f"run exceeded {limits.timeout_s:g}s")
    log.emit(
        SessionCompleted,
        stop_reason=state.stop_reason.value,
        answer=state.answer,
        error=state.error,
    )
    return state


async def _loop(state: AgentState, model: ModelProvider, registry: ToolRegistry, limits: Limits, log: _Log) -> None:
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
        log.emit(ModelCallRequested, iteration=state.iteration, message_count=len(state.messages))
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

        log.emit(
            ModelCallCompleted,
            iteration=state.iteration,
            content=reply.content,
            tool_calls=[{"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.tool_calls],
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

        if not reply.tool_calls:
            state.answer = reply.content or ""
            state.stop(StopReason.FINAL_ANSWER)
            return

        # Sequential for now; Phase 3 moves tool execution onto workers.
        for call in reply.tool_calls:
            started = time.time()
            log.emit(ToolCallRequested, call_id=call.id, name=call.name, arguments=call.arguments or {})
            result = await registry.dispatch(call)
            if result.is_error:
                log.emit(ToolCallFailed, call_id=call.id, name=call.name, error=result.content)
            else:
                log.emit(ToolCallCompleted, call_id=call.id, name=call.name, result=result.content)
            state.messages.append(Message("tool", result.content, tool_call_id=call.id, name=call.name))
            state.record(
                "tool",
                started,
                {"call_id": call.id, "name": call.name, "arguments": call.arguments, "is_error": result.is_error, "result": result.content},
            )
