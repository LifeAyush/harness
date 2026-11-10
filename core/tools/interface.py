"""What a tool is, as far as the harness is concerned.

A tool declares its arguments as a pydantic model. That one declaration gives
the JSON Schema the model sees and the validation the registry runs, so the two
can never drift apart.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pydantic import BaseModel

from core.model.interface import ToolSpec


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    timeout: ClassVar[float] = 10.0  # seconds; the registry enforces it

    def spec(self) -> ToolSpec:
        schema = self.Input.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)

    @abstractmethod
    async def run(self, args: BaseModel) -> ToolResult:
        """Do the work. Raise on failure; the registry turns exceptions into
        error results the model can read and react to."""


class ToolProvider(ABC):
    """A group of related tools that share setup, such as a root directory."""

    @abstractmethod
    def tools(self) -> Iterable[Tool]: ...
