import os

import pytest

from core.model.interface import ToolCall
from core.tools import registry as registry_module
from core.tools.registry import ToolRegistry
from tests.conftest import Echo


async def dispatch(registry, name, **arguments):
    return await registry.dispatch(ToolCall("t", name, arguments))


async def test_list_matches_pattern_and_skips_tooling_dirs(fs_registry):
    result = await dispatch(fs_registry, "filesystem.list", pattern="**/*.py")
    assert result.content.splitlines() == ["app/main.py", "app/users.py", "app/util.py"]


async def test_list_caps_results(fs_registry):
    result = await dispatch(fs_registry, "filesystem.list", pattern="**/*", max_results=2)
    assert "more than 2 matches" in result.content


async def test_read_prefixes_the_path(fs_registry):
    result = await dispatch(fs_registry, "filesystem.read", path="app/util.py")
    assert result.content.startswith("# app/util.py\ndef add")


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("filesystem.read", {"path": "../secret.txt"}),
        ("filesystem.read", {"path": "/etc/passwd"}),
        ("filesystem.list", {"pattern": "../*"}),
        ("filesystem.list", {"pattern": "/etc/*"}),
    ],
)
async def test_paths_cannot_leave_the_root(fs_registry, name, arguments):
    result = await dispatch(fs_registry, name, **arguments)
    assert result.is_error and "OutsideRoot" in result.content


async def test_symlinks_out_of_the_root_are_blocked(fs_registry, project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("token")
    os.symlink(outside, project / "app" / "link.txt")
    listed = await dispatch(fs_registry, "filesystem.list", pattern="app/*")
    assert "link.txt" not in listed.content
    read = await dispatch(fs_registry, "filesystem.read", path="app/link.txt")
    assert read.is_error and "token" not in read.content


async def test_binary_files_are_refused(fs_registry, project):
    (project / "blob.bin").write_bytes(b"\x00\x01\x02")
    result = await dispatch(fs_registry, "filesystem.read", path="blob.bin")
    assert result.is_error and "binary" in result.content


async def test_large_files_are_truncated(fs_registry, project):
    (project / "big.txt").write_text("x" * 5000)
    result = await dispatch(fs_registry, "filesystem.read", path="big.txt", max_bytes=100)
    assert "[truncated at 100 of 5000 bytes]" in result.content


def test_specs_come_from_the_input_model(fs_registry):
    read = {s.name: s for s in fs_registry.specs()}["filesystem.read"]
    assert read.parameters["required"] == ["path"]
    assert set(read.parameters["properties"]) == {"path", "max_bytes"}


def test_duplicate_names_are_rejected():
    with pytest.raises(ValueError, match="already registered"):
        ToolRegistry([Echo(), Echo()])


async def test_long_results_are_truncated(monkeypatch):
    monkeypatch.setattr(registry_module, "MAX_RESULT_CHARS", 10)
    result = await dispatch(ToolRegistry([Echo()]), "echo", text="a" * 25)
    assert result.content.startswith("a" * 10) and "15 more characters" in result.content
