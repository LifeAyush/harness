import asyncio

import pytest

from core.agent.agent import StopReason
from core.agent.loop import Limits, run
from core.model.interface import Message, ModelError, ModelProvider, ModelResponse, ToolCall, Usage
from core.model.scripted import DemoModel, ScriptedModel, answer, call, calls
from core.tools.registry import ToolRegistry
from tests.conftest import Boom, Echo, Slow


def tool_results(model: ScriptedModel, turn: int) -> list[Message]:
    return [m for m in model.seen[turn] if m.role == "tool"]


async def test_answers_without_tools():
    model = ScriptedModel([answer("4")])
    state = await run("what is 2 + 2?", model, ToolRegistry())
    assert state.stop_reason is StopReason.FINAL_ANSWER
    assert state.answer == "4"
    assert state.iteration == 1
    assert [s.kind for s in state.steps] == ["model"]
    assert [m.role for m in model.seen[0]] == ["system", "user"]


async def test_phase1_example_trace(fs_registry):
    """docs/phase1.md §4: list, read, answer, against real files."""
    state = await run("Find all Python files and tell me which contain FastAPI endpoints.", DemoModel(), fs_registry)
    assert state.stop_reason is StopReason.FINAL_ANSWER
    kinds = [(s.kind, s.data.get("name")) for s in state.steps]
    assert kinds[:2] == [("model", None), ("tool", "filesystem.list")]
    assert ("tool", "filesystem.read") in kinds and kinds[-1] == ("model", None)
    assert "app/main.py" in state.answer and "app/users.py" in state.answer
    assert "util.py" not in state.answer and ".venv" not in state.answer


async def test_tool_results_reach_the_model_with_their_call_ids():
    c = call("echo", text="hi")
    model = ScriptedModel([calls(c), answer("done")])
    state = await run("say hi", model, ToolRegistry([Echo()]))
    [result] = tool_results(model, 1)
    assert (result.content, result.tool_call_id, result.name) == ("hi", c.id, "echo")
    assert state.answer == "done"


async def test_adding_a_tool_needs_only_registration():
    registry = ToolRegistry()
    registry.register(Echo())
    model = ScriptedModel([calls(call("echo", text="plugged in")), answer("ok")])
    state = await run("use the new tool", model, registry)
    assert state.steps[1].data["result"] == "plugged in"


@pytest.mark.parametrize(
    "bad_call, expected",
    [
        (call("missing"), "unknown tool 'missing'"),
        (call("echo", wrong="x"), "invalid arguments for echo: text: Field required"),
        (ToolCall("c1", "echo", None, arguments_error="Expecting value"), "not a JSON object"),
        (call("boom"), "boom failed: RuntimeError: disk on fire"),
        (call("slow"), "slow timed out"),
    ],
)
async def test_tool_failures_go_back_to_the_model(bad_call, expected):
    model = ScriptedModel([calls(bad_call), answer("recovered")])
    state = await run("try it", model, ToolRegistry([Echo(), Boom(), Slow()]))
    [result] = tool_results(model, 1)
    assert expected in result.content
    assert state.steps[1].data["is_error"] is True
    assert state.stop_reason is StopReason.FINAL_ANSWER and state.answer == "recovered"


async def test_stops_at_max_iterations():
    model = ScriptedModel([calls(call("echo", text=str(i))) for i in range(10)])
    state = await run("loop forever", model, ToolRegistry([Echo()]), Limits(max_iterations=3))
    assert state.stop_reason is StopReason.MAX_ITERATIONS
    assert state.iteration == 3 and state.answer is None


async def test_stops_at_the_timeout():
    class Stuck(ModelProvider):
        name = "stuck"

        async def complete(self, messages, tools):
            await asyncio.sleep(5)

    state = await run("hang", Stuck(), ToolRegistry(), Limits(timeout_s=0.05))
    assert state.stop_reason is StopReason.TIMEOUT


async def test_stops_at_the_token_budget():
    expensive = ModelResponse(calls(call("echo", text="x")).message, Usage(900, 200))
    model = ScriptedModel([expensive, answer("never reached")])
    state = await run("spend", model, ToolRegistry([Echo()]), Limits(max_tokens=1000))
    assert state.stop_reason is StopReason.TOKEN_BUDGET
    assert state.iteration == 1 and state.usage.total == 1100


@pytest.mark.parametrize("error, text", [(ModelError("HTTP 401"), "HTTP 401"), (KeyError("choices"), "KeyError")])
async def test_model_failures_stop_cleanly(error, text):
    class Broken(ModelProvider):
        name = "broken"

        async def complete(self, messages, tools):
            raise error

    state = await run("anything", Broken(), ToolRegistry())
    assert state.stop_reason is StopReason.MODEL_ERROR and text in state.error


async def test_steps_are_serializable_in_order():
    model = ScriptedModel([calls(call("echo", text="a"), call("echo", text="b")), answer("ab")])
    state = await run("two calls", model, ToolRegistry([Echo()]))
    dicts = [s.to_dict() for s in state.steps]
    assert [d["index"] for d in dicts] == [0, 1, 2, 3]
    assert [d["kind"] for d in dicts] == ["model", "tool", "tool", "model"]
    assert all(d["duration_ms"] >= 0 for d in dicts)
