"""Event-sourced sessions (docs/phase2.md): a run is an ordered, append-only event log."""

from core.session.events import (
    Event,
    EventAdapter,
    ModelCallCompleted,
    ModelCallRequested,
    SessionCompleted,
    SessionCreated,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
)
from core.session.store import (
    EventStore,
    InMemoryEventStore,
    SequenceError,
    SequenceGapError,
    SequenceRewriteError,
)

__all__ = [
    "Event",
    "EventAdapter",
    "EventStore",
    "InMemoryEventStore",
    "ModelCallCompleted",
    "ModelCallRequested",
    "SequenceError",
    "SequenceGapError",
    "SequenceRewriteError",
    "SessionCompleted",
    "SessionCreated",
    "ToolCallCompleted",
    "ToolCallFailed",
    "ToolCallRequested",
]
