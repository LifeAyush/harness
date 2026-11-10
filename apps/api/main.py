"""HTTP entry point.

  HARNESS_MODEL  demo (default) or openai
  HARNESS_ROOT   directory the filesystem tools may read (default: current directory)

  uvicorn apps.api.main:app
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from apps.factory import build_model, build_registry
from core.agent.loop import Limits, run


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=8000)
    max_iterations: int = Field(10, ge=1, le=50)
    timeout_s: float = Field(120.0, gt=0, le=600)


class RunResponse(BaseModel):
    answer: str | None
    stop_reason: str
    error: str | None
    iterations: int
    usage: dict[str, int]
    steps: list[dict[str, Any]]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model = build_model(os.environ.get("HARNESS_MODEL", "demo"))
    app.state.registry = build_registry(os.environ.get("HARNESS_ROOT", "."))
    yield
    await app.state.model.aclose()


app = FastAPI(title="harness", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request):
    return {"status": "ok", "model": request.app.state.model.name, "tools": request.app.state.registry.names()}


@app.post("/v1/runs", response_model=RunResponse)
async def create_run(body: RunRequest, request: Request):
    state = await run(
        body.task,
        request.app.state.model,
        request.app.state.registry,
        Limits(max_iterations=body.max_iterations, timeout_s=body.timeout_s),
    )
    return RunResponse(
        answer=state.answer,
        stop_reason=state.stop_reason.value,
        error=state.error,
        iterations=state.iteration,
        usage={"prompt": state.usage.prompt_tokens, "completion": state.usage.completion_tokens},
        steps=[s.to_dict() for s in state.steps],
    )
