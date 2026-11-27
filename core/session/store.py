"""EventStore: append-only storage for run events.

The invariant (docs/phase2.md §2) is that ``(session_id, sequence_number)`` is
unique and gap-free: the next append for a session must carry exactly the next
sequence number. That makes ordering explicit, lets a writer detect a
concurrent writer, and keeps replay deterministic. The PostgreSQL/SQLite stores
planned later enforce the same rule with a UNIQUE constraint.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from core.session.events import Event


class SequenceError(ValueError):
    """An append did not carry the next sequence number for its session."""


class SequenceGapError(SequenceError):
    """The event skipped ahead: sequence_number is greater than the next expected."""


class SequenceRewriteError(SequenceError):
    """The event reuses a sequence number that is already stored."""


class EventStore(ABC):
    @abstractmethod
    def append(self, event: Event) -> None:
        """Append ``event``. Raises SequenceError unless it is the next one for its session."""

    @abstractmethod
    def read(self, session_id: str) -> list[Event]:
        """All events for the session in sequence order; empty if it has none."""


class InMemoryEventStore(EventStore):
    def __init__(self) -> None:
        self._logs: dict[str, list[Event]] = {}
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        with self._lock:
            log = self._logs.setdefault(event.session_id, [])
            expected = len(log)
            if event.sequence_number < expected:
                raise SequenceRewriteError(
                    f"session {event.session_id!r}: sequence {event.sequence_number} already stored (next is {expected})"
                )
            if event.sequence_number > expected:
                raise SequenceGapError(
                    f"session {event.session_id!r}: sequence {event.sequence_number} skips ahead (next is {expected})"
                )
            log.append(event)

    def read(self, session_id: str) -> list[Event]:
        with self._lock:
            return list(self._logs.get(session_id, ()))
