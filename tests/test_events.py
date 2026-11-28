import json
from datetime import timezone

import pytest
from pydantic import ValidationError

from core.session import (
    EventAdapter,
    InMemoryEventStore,
    SQLiteEventStore,
    ModelCallCompleted,
    ModelCallRequested,
    SequenceGapError,
    SequenceRewriteError,
    SessionCompleted,
    SessionCreated,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
)

ALL_EVENTS = [
    SessionCreated(session_id="r1", sequence_number=0, task="find endpoints", system_prompt="be brief"),
    ModelCallRequested(session_id="r1", sequence_number=1, iteration=1, message_count=2),
    ModelCallCompleted(
        session_id="r1",
        sequence_number=2,
        iteration=1,
        content=None,
        tool_calls=[{"id": "c1", "name": "grep", "arguments": {"pattern": "FastAPI"}}],
        prompt_tokens=12,
        completion_tokens=5,
    ),
    ToolCallRequested(session_id="r1", sequence_number=3, call_id="c1", name="grep", arguments={"pattern": "FastAPI"}),
    ToolCallCompleted(session_id="r1", sequence_number=4, call_id="c1", name="grep", result="app/main.py"),
    ToolCallFailed(session_id="r1", sequence_number=5, call_id="c2", name="read", error="no such file"),
    SessionCompleted(session_id="r1", sequence_number=6, stop_reason="final_answer", answer="app/main.py"),
]


@pytest.fixture(params=["memory", "sqlite"])
def new_store(request, tmp_path):
    """Factory for a fresh store of each kind; the contract tests below run against both."""
    opened = []

    def factory():
        store = InMemoryEventStore() if request.param == "memory" else SQLiteEventStore(tmp_path / f"{len(opened)}.db")
        opened.append(store)
        return store

    yield factory
    for store in opened:
        getattr(store, "close", lambda: None)()


def make(session_id: str, seq: int) -> ModelCallRequested:
    return ModelCallRequested(session_id=session_id, sequence_number=seq, iteration=1, message_count=1)


def test_every_event_type_is_covered():
    assert {e.type for e in ALL_EVENTS} == {
        "session_created",
        "model_call_requested",
        "model_call_completed",
        "tool_call_requested",
        "tool_call_completed",
        "tool_call_failed",
        "session_completed",
    }


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda e: e.type)
def test_round_trip_through_json(event):
    wire = json.loads(event.model_dump_json())  # what a persistent store would write
    assert EventAdapter.validate_python(wire) == event
    assert EventAdapter.validate_json(event.model_dump_json()) == event


def test_timestamp_defaults_to_utc():
    assert ALL_EVENTS[0].created_at.tzinfo is timezone.utc


def test_unknown_type_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        EventAdapter.validate_python({"type": "nope", "session_id": "r1", "sequence_number": 0})
    with pytest.raises(ValidationError):
        make("r1", 0).model_validate({**make("r1", 0).model_dump(), "surprise": 1})


def test_negative_sequence_and_empty_session_rejected():
    with pytest.raises(ValidationError):
        make("r1", -1)
    with pytest.raises(ValidationError):
        make("", 0)


def test_events_are_immutable():
    with pytest.raises(ValidationError):
        ALL_EVENTS[0].task = "changed"


def test_append_and_read_keep_order(new_store):
    store = new_store()
    for event in ALL_EVENTS:
        store.append(event)
    assert store.read("r1") == ALL_EVENTS
    assert [e.sequence_number for e in store.read("r1")] == list(range(7))


def test_read_unknown_session_is_empty(new_store):
    assert new_store().read("missing") == []


def test_first_event_must_be_zero(new_store):
    store = new_store()
    with pytest.raises(SequenceGapError):
        store.append(make("r1", 1))
    assert store.read("r1") == []


def test_gap_is_rejected_and_store_unchanged(new_store):
    store = new_store()
    store.append(make("r1", 0))
    with pytest.raises(SequenceGapError):
        store.append(make("r1", 2))
    assert [e.sequence_number for e in store.read("r1")] == [0]
    store.append(make("r1", 1))  # the right next one still works


def test_rewrite_is_rejected_and_original_kept(new_store):
    store = new_store()
    original = make("r1", 0)
    store.append(original)
    store.append(make("r1", 1))
    with pytest.raises(SequenceRewriteError):
        store.append(ModelCallRequested(session_id="r1", sequence_number=0, iteration=9, message_count=9))
    with pytest.raises(SequenceRewriteError):
        store.append(make("r1", 1))  # even an identical re-append is rejected
    assert store.read("r1")[0] == original
    assert len(store.read("r1")) == 2


def test_sessions_are_isolated(new_store):
    store = new_store()
    store.append(make("a", 0))
    store.append(make("b", 0))
    store.append(make("a", 1))
    assert [e.session_id for e in store.read("a")] == ["a", "a"]
    assert [e.session_id for e in store.read("b")] == ["b"]
    with pytest.raises(SequenceGapError):
        store.append(make("b", 2))  # b's next is 1, whatever a has


def test_read_returns_a_copy(new_store):
    store = new_store()
    store.append(make("r1", 0))
    store.read("r1").clear()
    assert len(store.read("r1")) == 1


def test_sqlite_events_survive_reopening(tmp_path):
    path = tmp_path / "events.db"
    first = SQLiteEventStore(path)
    for event in ALL_EVENTS:
        first.append(event)
    first.close()
    second = SQLiteEventStore(path)
    assert second.read("r1") == ALL_EVENTS
    second.append(make("r1", 7))  # appending continues where the log left off
    assert len(second.read("r1")) == 8
    second.close()
