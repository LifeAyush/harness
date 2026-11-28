"""Wiring shared by the API and the CLI."""

from __future__ import annotations

from pathlib import Path

from core.model.interface import ModelProvider
from core.model.openai_compat import OpenAICompatibleProvider
from core.model.scripted import DemoModel
from core.session.store import EventStore, InMemoryEventStore, SQLiteEventStore
from core.tools.filesystem import FilesystemTools
from core.tools.registry import ToolRegistry

MODELS = ("demo", "openai")
STORES = ("memory", "sqlite")
DEFAULT_EVENT_DB = "harness-events.db"


def build_model(kind: str) -> ModelProvider:
    """'demo' needs no key. 'openai' is any OpenAI-compatible API, configured by HARNESS_* variables."""
    if kind == "demo":
        return DemoModel()
    if kind == "openai":
        return OpenAICompatibleProvider.from_env()
    raise ValueError(f"unknown model {kind!r}; choose one of {', '.join(MODELS)}")


def build_registry(root: str | Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_provider(FilesystemTools(root))
    return registry


def build_store(kind: str = "memory", path: str | Path | None = None) -> EventStore:
    """'memory' (default) keeps events for the process lifetime; 'sqlite' persists them to ``path``."""
    if kind == "memory":
        return InMemoryEventStore()
    if kind == "sqlite":
        return SQLiteEventStore(path or DEFAULT_EVENT_DB)
    raise ValueError(f"unknown event store {kind!r}; choose one of {', '.join(STORES)}")
