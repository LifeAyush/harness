"""Read-only filesystem tools, confined to one root directory.

There is no sandbox until Phase 4, so these tools enforce their own boundary:
every path is resolved, symlinks included, and must stay inside the root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from core.tools.interface import Tool, ToolProvider, ToolResult

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache"}


class OutsideRoot(PermissionError):
    pass


class _Rooted:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise OutsideRoot(f"{relative!r} is outside the root")
        return candidate

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


class ListFiles(Tool, _Rooted):
    name = "filesystem.list"
    description = "List files under the project root that match a glob pattern, such as '**/*.py'. Returns one relative path per line."

    class Input(BaseModel):
        pattern: str = Field("**/*", description="Glob pattern relative to the root")
        max_results: int = Field(200, ge=1, le=2000)

    async def run(self, args: "ListFiles.Input") -> ToolResult:
        if args.pattern.startswith("/") or ".." in Path(args.pattern).parts:
            raise OutsideRoot("patterns must be relative and must not contain '..'")
        found = []
        for path in sorted(self.root.glob(args.pattern)):
            parts = path.relative_to(self.root).parts
            if any(p in SKIP_DIRS for p in parts) or not path.is_file():
                continue
            try:
                self.resolve(self.rel(path))
            except OutsideRoot:
                continue  # a symlink pointing outside the root
            found.append(self.rel(path))
            if len(found) > args.max_results:
                break
        if not found:
            return ToolResult(f"no files match {args.pattern!r}")
        more = len(found) > args.max_results
        lines = found[: args.max_results]
        return ToolResult("\n".join(lines) + (f"\n[more than {args.max_results} matches; narrow the pattern]" if more else ""))


class ReadFile(Tool, _Rooted):
    name = "filesystem.read"
    description = "Read a UTF-8 text file under the project root. The first line of the result is '# <path>'."

    class Input(BaseModel):
        path: str = Field(description="File path relative to the root")
        max_bytes: int = Field(20_000, ge=1, le=200_000)

    async def run(self, args: "ReadFile.Input") -> ToolResult:
        path = self.resolve(args.path)
        if not path.is_file():
            raise FileNotFoundError(f"{args.path} is not a file")
        data = path.read_bytes()
        if b"\x00" in data[:1024]:
            return ToolResult(f"{args.path} looks binary; not reading it", True)
        text = data[: args.max_bytes].decode("utf-8", errors="replace")
        note = f"\n[truncated at {args.max_bytes} of {len(data)} bytes]" if len(data) > args.max_bytes else ""
        return ToolResult(f"# {self.rel(path)}\n{text}{note}")


class FilesystemTools(ToolProvider):
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def tools(self) -> Iterable[Tool]:
        return [ListFiles(self.root), ReadFile(self.root)]
