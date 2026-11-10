import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from core.tools.filesystem import FilesystemTools
from core.tools.interface import Tool, ToolResult
from core.tools.registry import ToolRegistry


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A small project: two FastAPI modules, one plain module, and noise that must be skipped."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {}\n")
    (tmp_path / "app" / "users.py").write_text("from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.post('/users')\ndef create():\n    ...\n")
    (tmp_path / "app" / "util.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "site.py").write_text("@app.get('/ignored')\n")
    (tmp_path / "README.md").write_text("# demo\n")
    return tmp_path


@pytest.fixture()
def fs_registry(project: Path) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_provider(FilesystemTools(project))
    return registry


class Echo(Tool):
    name = "echo"
    description = "Echo the text back."

    class Input(BaseModel):
        text: str

    async def run(self, args):
        return ToolResult(args.text)


class Boom(Tool):
    name = "boom"
    description = "Always fails."

    class Input(BaseModel):
        pass

    async def run(self, args):
        raise RuntimeError("disk on fire")


class Slow(Tool):
    name = "slow"
    description = "Takes too long."
    timeout = 0.05

    class Input(BaseModel):
        pass

    async def run(self, args):
        await asyncio.sleep(1)
        return ToolResult("never")
