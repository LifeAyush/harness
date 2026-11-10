"""Run one task from the terminal and print the trace.

  python -m apps.cli "Find all Python files and tell me which contain FastAPI endpoints" --root .
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from apps.factory import MODELS, build_model, build_registry
from core.agent.agent import StopReason
from core.agent.loop import Limits, run


def _short(value, width=90) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    text = text.replace("\n", " ⏎ ")
    return text if len(text) <= width else text[: width - 1] + "…"


async def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness", description="Run the agent loop on one task.")
    p.add_argument("task")
    p.add_argument("--root", default=".", help="directory the filesystem tools may read")
    p.add_argument("--model", choices=MODELS, default="demo")
    p.add_argument("--max-iterations", type=int, default=10)
    p.add_argument("--timeout", type=float, default=120.0)
    args = p.parse_args(argv)

    try:
        model = build_model(args.model)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        state = await run(args.task, model, build_registry(args.root), Limits(args.max_iterations, args.timeout))
    finally:
        await model.aclose()

    for step in state.steps:
        d = step.data
        if step.kind == "model":
            calls = d["tool_calls"]
            if len(calls) > 3:
                names = sorted({c["name"] for c in calls})
                what = ", ".join(f"{n} ×{sum(c['name'] == n for c in calls)}" for n in names)
            else:
                what = ", ".join(f"{c['name']}({_short(c['arguments'], 40)})" for c in calls) or "answer"
            print(f"[{step.index:>2}] model  #{d['iteration']} → {what}")
        else:
            flag = "ERROR " if d["is_error"] else ""
            print(f"[{step.index:>2}] tool   {d['name']}: {flag}{_short(d['result'])}")
    print(f"\nstop: {state.stop_reason.value} · {state.iteration} model calls · ~{state.usage.total} tokens")
    if state.error:
        print(f"error: {state.error}")
    if state.answer is not None:
        print(f"\n{state.answer}")
    return 0 if state.stop_reason is StopReason.FINAL_ANSWER else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
