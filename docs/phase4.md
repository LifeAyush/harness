# Phase 4 — Sandbox

- **Status:** Planning
- **Goal:** Allow the agent to execute code safely.
- **Prev:** [phase3.md](phase3.md) · **Next:** [phase5.md](phase5.md)

## 1. Objective

The system must never become:

```text
LLM → arbitrary shell → host machine
```

Instead:

```text
Agent
 ↓
Tool Runtime
 ↓
Sandbox Manager
 ↓
Docker
 ↓
Container
```

Start with Docker.

## 2. Sandbox Contents

A sandbox may contain:

```text
/workspace
    └── repository
```

plus:

- Python
- Node
- Git
- Tests
- Dependencies

## 3. Restrictions

Enforce at minimum:

- filesystem boundaries
- network restrictions
- CPU limits
- memory limits
- execution timeouts
- process limits
- permissions

Tool calls from Phase 3 keep the same name and schema; only the provider changes from local execution to sandboxed execution.

## 4. Provider Abstraction

```text
SandboxProvider
    │
    ├── Docker
    ├── Kubernetes
    ├── Firecracker
    └── Remote Sandbox
```

Stable interface: `SandboxProvider` (see [overview.md](overview.md)).

Early code surface:

```text
core/sandbox/interface.py
core/sandbox/docker.py
core/policy/permissions.py
```

Responsibilities:

- create / reuse / destroy sandboxes per session or task
- mount repository and workspace
- enforce resource and permission policy before execution
- stream stdout / stderr back as tool results
- isolate failures so a bad command cannot take down the host or other sessions

## 5. Completion Criteria

The agent can safely:

- [ ] read repository
- [ ] modify repository
- [ ] run tests
- [ ] run shell commands
- [ ] inspect git state

without directly operating on the host environment.

## 6. Exit Criteria / Unlocks

- Every filesystem / shell / git tool runs through the sandbox manager.
- Phase 5 context and Phase 6 subagents can assume untrusted code is contained.
