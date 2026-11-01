import pytest
from pydantic import BaseModel
from agent.registry import ToolRegistry
from agent.types import ToolCall


# --- stub tool ---

class MoveArgs(BaseModel):
    x: int
    y: int

def move_fn(args: MoveArgs) -> dict:
    return {"moved_to": [args.x, args.y]}


# --- tests ---

def make_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register("move", MoveArgs, move_fn)
    return r


def test_dispatch_success():
    r = make_registry()
    result = r.dispatch(ToolCall(tool_name="move", args={"x": 3, "y": 5}))
    assert result.success
    assert result.output == {"moved_to": [3, 5]}
    assert result.error is None


def test_unknown_tool():
    r = make_registry()
    result = r.dispatch(ToolCall(tool_name="fly", args={}))
    assert not result.success
    assert "unknown tool" in result.error


def test_invalid_args():
    r = make_registry()
    result = r.dispatch(ToolCall(tool_name="move", args={"x": "not_an_int", "y": 5}))
    assert not result.success
    assert "invalid args" in result.error


def test_missing_args():
    r = make_registry()
    result = r.dispatch(ToolCall(tool_name="move", args={"x": 1}))  # missing y
    assert not result.success
    assert "invalid args" in result.error


def test_tool_raises():
    def bad_fn(args: MoveArgs):
        raise RuntimeError("hardware failure")

    r = ToolRegistry()
    r.register("move", MoveArgs, bad_fn)
    result = r.dispatch(ToolCall(tool_name="move", args={"x": 1, "y": 2}))
    assert not result.success
    assert "hardware failure" in result.error


def test_available():
    r = make_registry()
    assert "move" in r.available()
