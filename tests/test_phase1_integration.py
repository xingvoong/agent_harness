"""
Phase 1 integration test.

Wires AgentLoop + ToolRegistry + RetryController + ContextManager
together and runs a full mission: receive mission, call tools, handle
retries, track context, terminate with a structured result.
"""
import pytest
from pydantic import BaseModel

from agent.loop import AgentLoop, State
from agent.registry import ToolRegistry
from agent.retry import RetryController, RetryConfig
from agent.context import ContextManager
from agent.types import ToolCall


# ---------------------------------------------------------------------------
# Stub tools
# ---------------------------------------------------------------------------

class ScanArgs(BaseModel):
    radius: int

class MoveArgs(BaseModel):
    x: int
    y: int


def scan_fn(args: ScanArgs) -> dict:
    return {"targets_found": args.radius * 2, "clear": args.radius < 5}

def move_fn(args: MoveArgs) -> dict:
    return {"position": [args.x, args.y]}


# ---------------------------------------------------------------------------
# Helper: build the full Phase 1 stack
# ---------------------------------------------------------------------------

def build_stack(tool_configs: dict | None = None):
    registry = ToolRegistry()
    registry.register("scan", ScanArgs, scan_fn)
    registry.register("move", MoveArgs, move_fn)

    retry = RetryController(registry, configs=tool_configs or {})
    ctx = ContextManager(token_budget=2048)
    return registry, retry, ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_full_mission_completes():
    """Happy path: agent runs a 3-step mission and reaches DONE."""
    loop = AgentLoop(mission="scan radius 3, move to 2,2, scan radius 6")
    _, retry, ctx = build_stack()

    ctx.add("system", loop.mission)

    plan = [
        ToolCall("scan", {"radius": 3}),
        ToolCall("move", {"x": 2, "y": 2}),
        ToolCall("scan", {"radius": 6}),
    ]

    for call in plan:
        loop.transition(State.PLANNING)
        ctx.add("assistant", f"calling {call.tool_name} with {call.args}")

        loop.transition(State.TOOL_CALL)
        result = retry.dispatch(call)

        loop.transition(State.WAITING)
        loop.transition(State.OBSERVING)

        assert result.success, f"unexpected failure: {result.error}"
        ctx.add("user", f"result: {result.output}")

    loop.transition(State.PLANNING)
    loop.transition(State.DONE)

    assert loop.state == State.DONE
    assert loop.step > 0
    assert ctx.token_count > 0


def test_mission_fails_on_unknown_tool():
    """Agent calls a tool that doesn't exist — loop transitions to FAILED."""
    loop = AgentLoop(mission="use the teleporter")
    _, retry, ctx = build_stack()

    ctx.add("system", loop.mission)
    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)

    result = retry.dispatch(ToolCall("teleport", {"destination": "moon"}))

    assert not result.success
    loop.fail(result.error)

    assert loop.state == State.FAILED
    assert "unknown tool" in loop.failure_reason


def test_mission_recovers_from_flaky_tool():
    """Tool fails twice then succeeds — retry controller recovers, mission completes."""
    attempts = {"n": 0}

    def flaky_scan(args: ScanArgs) -> dict:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("sensor glitch")
        return {"targets_found": 4, "clear": True}

    registry = ToolRegistry()
    registry.register("scan", ScanArgs, flaky_scan)
    retry = RetryController(
        registry,
        configs={"scan": RetryConfig(max_retries=3, base_backoff=0.01)},
    )
    ctx = ContextManager()

    loop = AgentLoop(mission="scan with retries")
    ctx.add("system", loop.mission)

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)

    result = retry.dispatch(ToolCall("scan", {"radius": 2}))

    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)

    assert result.success
    assert attempts["n"] == 3
    ctx.add("user", f"result: {result.output}")

    loop.transition(State.PLANNING)
    loop.transition(State.DONE)

    assert loop.state == State.DONE


def test_context_accumulates_across_steps():
    """Context manager tracks the full conversation across multiple tool calls."""
    loop = AgentLoop(mission="multi-step scan")
    _, retry, ctx = build_stack()

    ctx.add("system", loop.mission)
    initial_tokens = ctx.token_count

    for i in range(3):
        loop.transition(State.PLANNING)
        ctx.add("assistant", f"step {i}: scanning")

        loop.transition(State.TOOL_CALL)
        result = retry.dispatch(ToolCall("scan", {"radius": i + 1}))

        loop.transition(State.WAITING)
        loop.transition(State.OBSERVING)
        ctx.add("user", f"observation {i}: {result.output}")

    assert ctx.token_count > initial_tokens
    assert len(ctx.messages) == 7  # system + 3 assistant + 3 user


def test_human_injection_mid_mission():
    """Operator injects an observation mid-mission — tagged HUMAN, visible to agent."""
    loop = AgentLoop(mission="navigate to objective")
    _, retry, ctx = build_stack()

    ctx.add("system", loop.mission)

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)
    result = retry.dispatch(ToolCall("move", {"x": 1, "y": 1}))
    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)
    ctx.add("user", f"result: {result.output}")

    # operator injects a correction
    ctx.add("user", "obstacle at 2,2 — reroute via 3,1", source="HUMAN")

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)
    result = retry.dispatch(ToolCall("move", {"x": 3, "y": 1}))
    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)
    ctx.add("user", f"result: {result.output}")

    loop.transition(State.PLANNING)
    loop.transition(State.DONE)

    human_msgs = [m for m in ctx.messages if m.source == "HUMAN"]
    assert len(human_msgs) == 1
    assert "reroute" in human_msgs[0].content
    assert loop.state == State.DONE


def test_invalid_args_fails_mission():
    """Bad tool args fail at the registry boundary before any execution."""
    loop = AgentLoop(mission="bad args test")
    _, retry, ctx = build_stack()

    ctx.add("system", loop.mission)
    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)

    result = retry.dispatch(ToolCall("scan", {"radius": "not_a_number"}))

    assert not result.success
    assert "invalid args" in result.error

    loop.fail(result.error)
    assert loop.state == State.FAILED
