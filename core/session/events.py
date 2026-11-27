"""Event types for one run (docs/phase2.md §2-3).

Every event carries ``session_id`` (the run), a ``sequence_number`` that starts
at 0 and increases by one, and a UTC timestamp. The ``type`` field is the
discriminator, so a stored event can be parsed back with ``EventAdapter``.

Lifecycle of a run::

    session_created
      model_call_requested -> model_call_completed
        tool_call_requested -> tool_call_completed | tool_call_failed
        ...
    session_completed (stop reason)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _EventBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    sequence_number: int = Field(ge=0)
    created_at: datetime = Field(default_factory=_now)


class SessionCreated(_EventBase):
    type: Literal["session_created"] = "session_created"
    task: str
    system_prompt: str


class ModelCallRequested(_EventBase):
    type: Literal["model_call_requested"] = "model_call_requested"
    iteration: int = Field(ge=1)  # 1-based count of model calls in the run
    message_count: int = Field(ge=0)  # messages in the context sent to the model


class ModelCallCompleted(_EventBase):
    type: Literal["model_call_completed"] = "model_call_completed"
    iteration: int = Field(ge=1)
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)  # {id, name, arguments}
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class ToolCallRequested(_EventBase):
    type: Literal["tool_call_requested"] = "tool_call_requested"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallCompleted(_EventBase):
    type: Literal["tool_call_completed"] = "tool_call_completed"
    call_id: str
    name: str
    result: str


class ToolCallFailed(_EventBase):
    type: Literal["tool_call_failed"] = "tool_call_failed"
    call_id: str
    name: str
    error: str


class SessionCompleted(_EventBase):
    type: Literal["session_completed"] = "session_completed"
    stop_reason: Literal["final_answer", "max_iterations", "timeout", "token_budget", "model_error"]
    answer: str | None = None
    error: str | None = None


Event = Annotated[
    SessionCreated
    | ModelCallRequested
    | ModelCallCompleted
    | ToolCallRequested
    | ToolCallCompleted
    | ToolCallFailed
    | SessionCompleted,
    Field(discriminator="type"),
]

# Parse a dict or JSON string into the right event class: EventAdapter.validate_python(d)
EventAdapter: TypeAdapter[Event] = TypeAdapter(Event)
