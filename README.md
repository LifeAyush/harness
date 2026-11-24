# harness

[![ci](https://github.com/LifeAyush/harness/actions/workflows/ci.yml/badge.svg)](https://github.com/LifeAyush/harness/actions/workflows/ci.yml)

An agent runtime built from first principles: the infrastructure that turns an LLM into an agent that uses tools, keeps state and stops reliably. No LangChain, no LangGraph. The loop, tool registry and provider boundary are written here, so each one can be understood and replaced.

```text
Agent capability ≈ model + harness + environment + state
```

**Status: Phase 1 of 8, the agent loop.** The roadmap is in [docs/overview.md](docs/overview.md). Later phases add event-sourced sessions, tool workers, a Docker sandbox, a context engine, subagents, plugins and a distributed deployment.

## What works now

- **Agent loop** ([core/agent/loop.py](core/agent/loop.py)). Model → tool calls → results → model, until there's a final answer. Every run ends in one of: final answer, `max_iterations`, wall-clock timeout, token budget, or model error. Each model and tool call is recorded as a step, ready to become an event in Phase 2.
- **Tools** ([core/tools](core/tools)). A tool is a name, a description, a pydantic input model and an async `run`. The input model provides both the JSON Schema the model sees and the validation, so they can't drift apart. The registry turns unknown tools, bad arguments, exceptions and timeouts into error results that go back to the model, which can then correct itself. Adding a tool is one `register` call; the loop doesn't change.
- **Filesystem tools.** `filesystem.list` and `filesystem.read`, confined to one root directory. Path traversal and symlinks out of the root are blocked, binary files are refused, and output is capped.
- **Model providers** ([core/model](core/model)):
  - `OpenAICompatibleProvider` works with DeepSeek (default), OpenAI, or any `/chat/completions` server with tool calling. It retries 429 and 5xx responses, and maps dotted tool names to wire-safe ones and back.
  - `ScriptedModel` replays fixed turns, for tests.
  - `DemoModel` follows a hard-coded plan for the example task, so everything runs without an API key. It pattern-matches source; it doesn't reason.
- **API and CLI.** `POST /v1/runs` and `python -m apps.cli` both return the answer, the stop reason, token usage and the full step trace.

Not verified yet: a live run against a real model. The provider is tested against a mocked HTTP transport only.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Example task from [docs/phase1.md](docs/phase1.md), with the keyless demo model:

```console
$ python -m apps.cli "Find all Python files and tell me which contain FastAPI endpoints" --root ../some-fastapi-project
[ 0] model  #1 → filesystem.list({"pattern": "**/*.py"})
[ 1] tool   filesystem.list: app/__init__.py ⏎ app/auth.py ⏎ app/main.py ⏎ app/routes/api.py ⏎ …
[ 2] model  #2 → filesystem.read ×17
[ 3] tool   filesystem.read: # app/__init__.py ⏎
…
stop: final_answer · 3 model calls · ~11523 tokens

These files define FastAPI endpoints:
- app/main.py
- app/routes/api.py
- app/routes/terminal.py
```

With a real model:

```bash
export HARNESS_API_KEY=...                            # DeepSeek by default
export HARNESS_BASE_URL=https://api.openai.com/v1     # optional: OpenAI or another compatible server
export HARNESS_MODEL_NAME=gpt-4o-mini                 # optional
python -m apps.cli "…" --model openai --root .
```

API:

```bash
HARNESS_MODEL=demo HARNESS_ROOT=. uvicorn apps.api.main:app
curl -s localhost:8000/v1/runs -H 'content-type: application/json' -d '{"task": "Which files define FastAPI routes?"}'
```

## Layout

```text
core/agent/    run loop, per-run state and step trace
core/model/    ModelProvider interface, OpenAI-compatible, scripted and demo models
core/tools/    Tool interface, registry, filesystem tools
apps/          FastAPI app and CLI
docs/          architecture overview and the eight phases
tests/         loop, tools, provider and API tests
```

## License

MIT

---

Building something similar, or stuck on an agent loop or tool calling? Happy to dig in with you: [grab 30 min](https://cal.com/ayush-patil-s2zg3v/30min).
