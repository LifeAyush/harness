# Phase 7 — Plugin Runtime

- **Status:** Planning
- **Goal:** Move from a modular agent system to a DeepSeek-style composable harness.
- **Prev:** [phase6.md](phase6.md) · **Next:** [phase8.md](phase8.md)

## 1. Objective

Components become replaceable plugins:

```text
Runtime
    │
    └── Plugin Registry
          │
          ├── Model
          ├── Tools
          ├── Storage
          ├── Sandbox
          ├── Context
          ├── Loop
          └── Scheduler
```

Core principle:

> The core runtime should not own every concrete capability. Plugins provide capabilities to the runtime.

This is where the project begins approaching the DeepSeek Harness architecture rather than simply being an agent framework.

## 2. Plugin Model

A plugin conceptually provides:

- metadata
- dependencies
- services
- events
- tools

Cordis-style responsibilities:

- load plugin
- resolve dependencies
- register services
- subscribe to events
- unload plugin

Destination layout:

```text
plugins/
├── models/
├── tools/
├── sandboxes/
└── storage/
```

## 3. Swaps Enabled

```text
OpenAI
   ↓
DeepSeek
```

```text
Docker
   ↓
Kubernetes
```

```text
Redis
   ↓
Kafka
```

All through provider / plugin implementations, without rewriting the agent runtime. This is only possible because Phases 1–6 kept interfaces stable (`ModelProvider`, `Tool`, `ToolProvider`, `SessionStore`, `SandboxProvider`, `EventBus`, `ContextEngine`).

## 4. Completion Criteria

- [ ] major components can be replaced without rewriting the agent runtime
- [ ] model backends swap via plugin
- [ ] sandbox backends swap via plugin
- [ ] queue / event-bus backends swap via plugin
- [ ] plugin lifecycle (load, dependency resolution, registration, event subscription, unload) works

## 5. Exit Criteria / Unlocks

- The harness is composable.
- Phase 8 can focus on production topology and distributed concerns rather than rewiring core code.
