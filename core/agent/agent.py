"""State for one run: the context sent to the model, plus a trace of every step.

The trace is shaped like an event log on purpose. Phase 2 persists each Step
as a session event, so a run can be replayed and resumed.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from core.model.interface import Message, Usage

DEFAULT_SYSTEM_PROMPT = (
    "You are an agent working inside a project directory. Use the tools to inspect "
    "files instead of guessing. When you have enough information, answer directly "
    "and concisely without calling more tools."
)


class StopReason(str, Enum):
    FINAL_ANSWER = "final_answer"
    MAX_ITERATIONS = "max_iterations"
    TIMEOUT = "timeout"
    TOKEN_BUDGET = "token_budget"
    MODEL_ERROR = "model_error"


@dataclass
class Step:
    index: int
    kind: str  # "model" or "tool"
    started_at: float
    duration_ms: float
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentState:
    task: str
    messages: list[Message]
    iteration: int = 0  # model calls made so far
    usage: Usage = field(default_factory=Usage)
    steps: list[Step] = field(default_factory=list)
    answer: str | None = None
    stop_reason: StopReason | None = None
    error: str | None = None

    @classmethod
    def start(cls, task: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> "AgentState":
        return cls(task=task, messages=[Message("system", system_prompt), Message("user", task)])

    def record(self, kind: str, started_at: float, data: dict[str, Any]) -> None:
        self.steps.append(Step(len(self.steps), kind, started_at, round((time.time() - started_at) * 1000, 2), data))

    def stop(self, reason: StopReason, error: str | None = None) -> None:
        self.stop_reason = reason
        self.error = error

    @property
    def done(self) -> bool:
        return self.stop_reason is not None
