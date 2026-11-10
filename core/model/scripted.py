"""Models that need no API key.

ScriptedModel replays a fixed list of turns, for tests. DemoModel follows a
hard-coded plan for the example task in docs/phase1.md (find the Python files
that define FastAPI endpoints), so the whole harness can be run end to end
without an LLM. Neither one reasons: they stand in for a model so the loop,
the registry and the tools can be exercised for real.
"""

from __future__ import annotations

import json
import re
from itertools import count
from typing import Callable, Sequence, Union

from core.model.interface import Message, ModelError, ModelProvider, ModelResponse, ToolCall, ToolSpec, Usage

Turn = Union[ModelResponse, Callable[[Sequence[Message]], ModelResponse]]


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _usage(messages: Sequence[Message], reply: Message) -> Usage:
    prompt = sum(estimate_tokens(m.content or "") for m in messages)
    completion = estimate_tokens(reply.content or "") + sum(
        estimate_tokens(json.dumps(c.arguments or {})) for c in reply.tool_calls
    )
    return Usage(prompt, completion)


def answer(text: str) -> ModelResponse:
    return ModelResponse(Message("assistant", text), finish_reason="stop")


_ids = count(1)


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(id=f"call_{next(_ids)}", name=name, arguments=arguments)


def calls(*tool_calls: ToolCall) -> ModelResponse:
    return ModelResponse(Message("assistant", None, tuple(tool_calls)), finish_reason="tool_calls")


class ScriptedModel(ModelProvider):
    """Returns the given turns in order. Raises ModelError when it runs out."""

    name = "scripted"

    def __init__(self, turns: Sequence[Turn]):
        self.turns = list(turns)
        self.seen: list[list[Message]] = []  # the context sent on each call

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelResponse:
        self.seen.append(list(messages))
        if not self.turns:
            raise ModelError("scripted model has no turns left")
        turn = self.turns.pop(0)
        resp = turn(messages) if callable(turn) else turn
        if resp.usage.total == 0:
            resp = ModelResponse(resp.message, _usage(messages, resp.message), resp.finish_reason)
        return resp


ROUTE = re.compile(r"@(?:\w+)\.(?:get|post|put|patch|delete|websocket)\(|APIRouter\(|FastAPI\(")


class DemoModel(ModelProvider):
    """Deterministic stand-in for the docs/phase1.md example.

    Turn 1 lists *.py files. Turn 2 reads them. Turn 3 answers with the files
    whose source defines FastAPI apps, routers or routes.
    """

    name = "demo"

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelResponse:
        tool_msgs = [m for m in messages if m.role == "tool"]
        listed = [m for m in tool_msgs if m.name == "filesystem.list"]
        reads = [m for m in tool_msgs if m.name == "filesystem.read"]

        if not listed:
            reply = calls(call("filesystem.list", pattern="**/*.py"))
        elif not reads:
            files = [line for line in (listed[-1].content or "").splitlines() if line.endswith(".py")]
            if not files:
                reply = answer("There are no Python files under the root.")
            else:
                reply = calls(*(call("filesystem.read", path=f) for f in files[:20]))
        else:
            hits = []
            for m in reads:
                path, _, body = (m.content or "").partition("\n")
                if ROUTE.search(body):
                    hits.append(path.removeprefix("# "))
            if hits:
                reply = answer("These files define FastAPI endpoints:\n" + "\n".join(f"- {h}" for h in hits))
            else:
                reply = answer("None of the Python files define FastAPI endpoints.")
        return ModelResponse(reply.message, _usage(messages, reply.message), reply.finish_reason)
