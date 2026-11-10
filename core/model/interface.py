"""The boundary between the harness and any LLM.

The loop only ever sees these types. A provider translates them to and from
its own wire format, so swapping OpenAI for DeepSeek, Anthropic or a local
model never touches the loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None
    # Set when the model sent arguments that are not a JSON object. The
    # registry reports it back to the model instead of crashing the loop.
    arguments_error: str | None = None


@dataclass(frozen=True)
class Message:
    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # role == "tool": which call this answers
    name: str | None = None  # role == "tool": which tool produced it


@dataclass(frozen=True)
class ToolSpec:
    """What the model is told about a tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments object


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.prompt_tokens + other.prompt_tokens, self.completion_tokens + other.completion_tokens)


@dataclass(frozen=True)
class ModelResponse:
    message: Message  # always role == "assistant"
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


class ModelError(Exception):
    """The provider could not produce a response (network, auth, bad payload)."""


class ModelProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelResponse:
        """One model turn: given the conversation and the available tools,
        return either a final answer or one or more tool calls."""

    async def aclose(self) -> None:
        return None
