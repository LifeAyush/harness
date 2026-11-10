"""Wiring shared by the API and the CLI."""

from __future__ import annotations

from pathlib import Path

from core.model.interface import ModelProvider
from core.model.openai_compat import OpenAICompatibleProvider
from core.model.scripted import DemoModel
from core.tools.filesystem import FilesystemTools
from core.tools.registry import ToolRegistry

MODELS = ("demo", "openai")


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
