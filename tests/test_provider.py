import json

import httpx
import pytest

from core.model.interface import Message, ModelError, ToolCall, ToolSpec
from core.model.openai_compat import OpenAICompatibleProvider, to_wire_name

KEY = "sk-test-not-real"
SPECS = [ToolSpec("filesystem.read", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})]


def provider(handler) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(base_url="https://api.example.test/v1", transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(KEY, model="deepseek-chat", max_retries=2, client=client)


def completion(message: dict, usage=(12, 5), finish="stop") -> dict:
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}}


async def test_request_uses_wire_safe_names_and_encodes_history():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion({"role": "assistant", "content": "ok"}))

    history = [
        Message("system", "be brief"),
        Message("user", "read it"),
        Message("assistant", None, (ToolCall("c1", "filesystem.read", {"path": "a.py"}),)),
        Message("tool", "# a.py\nx = 1", tool_call_id="c1", name="filesystem.read"),
    ]
    resp = await provider(handler).complete(history, SPECS)

    body = seen["body"]
    assert seen["auth"] == f"Bearer {KEY}"
    assert body["model"] == "deepseek-chat" and body["tool_choice"] == "auto"
    assert body["tools"][0]["function"]["name"] == "filesystem__read"
    assert body["messages"][2]["tool_calls"][0]["function"] == {"name": "filesystem__read", "arguments": '{"path": "a.py"}'}
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": "# a.py\nx = 1"}
    assert resp.message.content == "ok" and resp.usage.total == 17


async def test_tool_calls_are_mapped_back_and_bad_arguments_flagged():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "filesystem__read", "arguments": '{"path": "x.py"}'}},
            {"id": "b", "type": "function", "function": {"name": "filesystem__read", "arguments": "{not json"}},
            {"id": "c", "type": "function", "function": {"name": "filesystem__read", "arguments": "[1, 2]"}},
        ],
    }
    resp = await provider(lambda r: httpx.Response(200, json=completion(message, finish="tool_calls"))).complete([Message("user", "go")], SPECS)
    good, bad_json, not_object = resp.message.tool_calls
    assert (good.name, good.arguments, good.arguments_error) == ("filesystem.read", {"path": "x.py"}, None)
    assert bad_json.arguments is None and bad_json.arguments_error
    assert not_object.arguments is None and "list" in not_object.arguments_error
    assert resp.finish_reason == "tool_calls"


async def test_retries_rate_limits_then_succeeds(monkeypatch):
    monkeypatch.setattr("core.model.openai_compat.asyncio.sleep", lambda s: _noop())
    statuses = iter([429, 503, 200])

    def handler(request):
        code = next(statuses)
        return httpx.Response(code, json=completion({"role": "assistant", "content": "finally"}) if code == 200 else {"error": "busy"})

    resp = await provider(handler).complete([Message("user", "hi")], [])
    assert resp.message.content == "finally"


async def test_auth_errors_are_not_retried_and_do_not_leak_the_key():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    with pytest.raises(ModelError) as err:
        await provider(handler).complete([Message("user", "hi")], [])
    assert len(calls) == 1 and "HTTP 401" in str(err.value) and KEY not in str(err.value)


async def test_network_errors_become_model_errors(monkeypatch):
    monkeypatch.setattr("core.model.openai_compat.asyncio.sleep", lambda s: _noop())

    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ModelError, match="ConnectError"):
        await provider(handler).complete([Message("user", "hi")], [])


async def test_unexpected_shape_is_a_model_error():
    with pytest.raises(ModelError, match="unexpected response shape"):
        await provider(lambda r: httpx.Response(200, json={"choices": []})).complete([Message("user", "hi")], [])


def test_names_that_cannot_be_sent_are_rejected():
    assert to_wire_name("git.diff-stat") == "git__diff-stat"
    with pytest.raises(ValueError):
        to_wire_name("has space")


def test_a_key_is_required():
    with pytest.raises(ValueError, match="HARNESS_API_KEY"):
        OpenAICompatibleProvider("")


async def _noop():
    return None
