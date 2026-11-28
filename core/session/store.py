"""EventStore: append-only storage for run events.

The invariant (docs/phase2.md §2) is that ``(session_id, sequence_number)`` is
unique and gap-free: the next append for a session must carry exactly the next
sequence number. That makes ordering explicit, lets a writer detect a
concurrent writer, and keeps replay deterministic. The SQLite store enforces the
same rule with a primary key; a PostgreSQL store (docs/phase2.md) would do likewise.
"""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from core.session.events import Event, EventAdapter


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


class SQLiteEventStore(EventStore):
    """Durable store on the standard-library ``sqlite3``.

    One table keyed by ``(session_id, sequence_number)``; the event is stored as
    JSON. Rows are only ever inserted. The PRIMARY KEY is the same uniqueness
    rule the in-memory store checks by hand, so a second writer racing for the
    same sequence number fails instead of overwriting.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            " session_id TEXT NOT NULL,"
            " sequence_number INTEGER NOT NULL,"
            " type TEXT NOT NULL,"
            " payload TEXT NOT NULL,"
            " PRIMARY KEY (session_id, sequence_number))"
        )

    def append(self, event: Event) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT COUNT(*) FROM events WHERE session_id = ?", (event.session_id,)
                ).fetchone()
                expected = row[0]
                if event.sequence_number < expected:
                    raise SequenceRewriteError(
                        f"session {event.session_id!r}: sequence {event.sequence_number} already stored (next is {expected})"
                    )
                if event.sequence_number > expected:
                    raise SequenceGapError(
                        f"session {event.session_id!r}: sequence {event.sequence_number} skips ahead (next is {expected})"
                    )
                self._db.execute(
                    "INSERT INTO events (session_id, sequence_number, type, payload) VALUES (?, ?, ?, ?)",
                    (event.session_id, event.sequence_number, event.type, event.model_dump_json()),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def read(self, session_id: str) -> list[Event]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM events WHERE session_id = ? ORDER BY sequence_number", (session_id,)
            ).fetchall()
        return [EventAdapter.validate_json(r[0]) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._db.close()
