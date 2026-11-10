"""Provider for any OpenAI-compatible chat completions API (DeepSeek, OpenAI, vLLM, Ollama…).

Configuration from the environment (see from_env):
  HARNESS_API_KEY     bearer token
  HARNESS_BASE_URL    default https://api.deepseek.com/v1
  HARNESS_MODEL_NAME  default deepseek-chat
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Sequence

import httpx

from core.model.interface import Message, ModelError, ModelProvider, ModelResponse, ToolCall, ToolSpec, Usage

# Function names on the wire must match ^[a-zA-Z0-9_-]{1,64}$, so
# "filesystem.read" travels as "filesystem__read" and is mapped back.
_WIRE_SAFE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
RETRY_STATUS = {429, 500, 502, 503, 504}


def to_wire_name(name: str) -> str:
    wire = name.replace(".", "__")
    if not _WIRE_SAFE.match(wire):
        raise ValueError(f"tool name {name!r} cannot be sent to an OpenAI-compatible API")
    return wire


class OpenAICompatibleProvider(ModelProvider):
    name = "openai-compatible"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        timeout_s: float = 60.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("an API key is required; set HARNESS_API_KEY")
        self.model = model
        self.max_retries = max_retries
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider":
        return cls(
            api_key=os.environ.get("HARNESS_API_KEY", ""),
            base_url=os.environ.get("HARNESS_BASE_URL", "https://api.deepseek.com/v1"),
            model=os.environ.get("HARNESS_MODEL_NAME", "deepseek-chat"),
        )

    # -- request -------------------------------------------------------------

    @staticmethod
    def encode_message(m: Message) -> dict[str, Any]:
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": to_wire_name(c.name), "arguments": json.dumps(c.arguments or {})},
                }
                for c in m.tool_calls
            ]
        return out

    def build_request(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": [self.encode_message(m) for m in messages]}
        if tools:
            body["tools"] = [
                {"type": "function", "function": {"name": to_wire_name(t.name), "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
            body["tool_choice"] = "auto"
        return body

    # -- response ------------------------------------------------------------

    @staticmethod
    def decode_response(data: dict[str, Any], names: dict[str, str]) -> ModelResponse:
        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError(f"unexpected response shape: {str(data)[:200]}")
        calls = []
        for raw in msg.get("tool_calls") or []:
            fn = raw.get("function", {})
            wire = fn.get("name", "")
            arguments: dict[str, Any] | None = None
            error = None
            try:
                parsed = json.loads(fn.get("arguments") or "{}")
                if isinstance(parsed, dict):
                    arguments = parsed
                else:
                    error = f"got {type(parsed).__name__}"
            except json.JSONDecodeError as exc:
                error = str(exc)
            calls.append(ToolCall(id=raw.get("id", ""), name=names.get(wire, wire), arguments=arguments, arguments_error=error))
        usage = data.get("usage") or {}
        return ModelResponse(
            Message("assistant", msg.get("content"), tuple(calls)),
            Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            choice.get("finish_reason"),
        )

    # -- call ----------------------------------------------------------------

    async def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> ModelResponse:
        body = self.build_request(messages, tools)
        names = {to_wire_name(t.name): t.name for t in tools}
        last: str = ""
        for attempt in range(self.max_retries + 1):
            try:
                res = await self._client.post("/chat/completions", json=body, headers=self._headers)
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if res.status_code < 400:
                    return self.decode_response(res.json(), names)
                last = f"HTTP {res.status_code}: {res.text[:300]}"
                if res.status_code not in RETRY_STATUS:
                    break
            if attempt < self.max_retries:
                await asyncio.sleep(0.5 * 2**attempt)
        raise ModelError(last)

    async def aclose(self) -> None:
        await self._client.aclose()
