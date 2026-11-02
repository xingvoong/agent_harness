"""
Phase 2 integration test.

Shows how Phase 1 (AgentLoop, ToolRegistry, RetryController, ContextManager)
connects to Phase 2 (WorldState, HAL, CommandQueue).

The bridge: tool functions registered in the ToolRegistry now call into the
HAL (SimActuator / SimSensor) instead of returning stub data. The agent loop
doesn't know or care — it just dispatches ToolCalls and gets ToolResults back.

  AgentLoop
      │ ToolCall
      ▼
  RetryController
      │
      ▼
  ToolRegistry  ──► tool fn ──► SimActuator / SimSensor ──► WorldState
      │
      ▼ ToolResult
  ContextManager (records observation)
"""
import asyncio
import pytest
from pydantic import BaseModel

from agent.loop import AgentLoop, State
from agent.registry import ToolRegistry
from agent.retry import RetryController, RetryConfig
from agent.context import ContextManager
from agent.types import ToolCall

from sim.world import WorldState, Entity, EntityType
from hal.sim import SimActuator, SimSensor
from hal.queue import CommandQueue
from hal.types import MoveCommand, PickUpCommand, SensorQuery


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

class MoveArgs(BaseModel):
    x: int
    y: int

class PickUpArgs(BaseModel):
    resource_id: str

class ScanArgs(BaseModel):
    radius: int


# ---------------------------------------------------------------------------
# Build the full stack: Phase 1 wired to Phase 2 HAL
# ---------------------------------------------------------------------------

def build_stack():
    world = WorldState(width=10, height=10)
    world.add_entity(Entity("agent1", EntityType.AGENT,     0, 0))
    world.add_entity(Entity("res1",   EntityType.RESOURCE,  3, 3))
    world.add_entity(Entity("obj1",   EntityType.OBJECTIVE, 7, 7))
    world.add_entity(Entity("wall1",  EntityType.OBSTACLE,  5, 5))

    actuator = SimActuator(world)
    sensor   = SimSensor(world)

    def move_tool(args: MoveArgs):
        r = actuator.execute(MoveCommand(agent_id="agent1", x=args.x, y=args.y))
        if not r.success:
            raise RuntimeError(r.error)
        return {"position": [args.x, args.y]}

    def pick_up_tool(args: PickUpArgs):
        r = actuator.execute(PickUpCommand(agent_id="agent1", resource_id=args.resource_id))
        if not r.success:
            raise RuntimeError(r.error)
        return {"picked_up": args.resource_id}

    def scan_tool(args: ScanArgs):
        obs = sensor.read(SensorQuery(agent_id="agent1", radius=args.radius))
        return {
            "position": obs.position,
            "nearby": [{"id": e.id, "type": e.type, "x": e.x, "y": e.y} for e in obs.nearby],
            "tick": obs.tick,
        }

    registry = ToolRegistry()
    registry.register("move",    MoveArgs,    move_tool)
    registry.register("pick_up", PickUpArgs,  pick_up_tool)
    registry.register("scan",    ScanArgs,    scan_tool)

    retry = RetryController(registry)
    ctx   = ContextManager(token_budget=4096)

    return world, registry, retry, ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_navigates_and_picks_up():
    """Full mission: move to resource, pick it up, reach objective."""
    world, _, retry, ctx = build_stack()
    loop = AgentLoop(mission="move to res1, pick it up, reach obj1")
    ctx.add("system", loop.mission)

    steps = [
        ToolCall("move",    {"x": 3, "y": 3}),
        ToolCall("pick_up", {"resource_id": "res1"}),
        ToolCall("move",    {"x": 7, "y": 7}),
    ]

    for call in steps:
        loop.transition(State.PLANNING)
        loop.transition(State.TOOL_CALL)
        result = retry.dispatch(call)
        loop.transition(State.WAITING)
        loop.transition(State.OBSERVING)

        assert result.success, f"{call.tool_name} failed: {result.error}"
        ctx.add("user", f"observation: {result.output}")

    loop.transition(State.PLANNING)
    loop.transition(State.DONE)

    assert loop.state == State.DONE
    assert world.get("agent1").x == 7
    assert world.get("agent1").y == 7
    assert world.get("res1").held_by == "agent1"


def test_sensor_feeds_context():
    """Scan result is real world data — nearby entities appear in context."""
    world, _, retry, ctx = build_stack()
    loop = AgentLoop(mission="scan and report")
    ctx.add("system", loop.mission)

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)
    result = retry.dispatch(ToolCall("scan", {"radius": 9}))
    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)

    assert result.success
    ctx.add("user", f"observation: {result.output}")

    # observation contains real entity data from world state
    obs_text = str(result.output)
    assert "res1" in obs_text
    assert "obj1" in obs_text
    assert "wall1" in obs_text


def test_obstacle_blocks_agent():
    """Agent can't move into obstacle — HAL returns failure, loop goes to FAILED."""
    world, _, retry, ctx = build_stack()
    loop = AgentLoop(mission="walk into wall")
    ctx.add("system", loop.mission)

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)
    result = retry.dispatch(ToolCall("move", {"x": 5, "y": 5}))
    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)

    assert not result.success
    loop.fail(result.error)

    assert loop.state == State.FAILED
    assert world.get("agent1").x == 0   # agent didn't move


def test_pick_up_wrong_position_fails():
    """Agent must be at resource location to pick it up."""
    world, _, retry, ctx = build_stack()
    loop = AgentLoop(mission="pick up from distance")
    ctx.add("system", loop.mission)

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)
    result = retry.dispatch(ToolCall("pick_up", {"resource_id": "res1"}))

    assert not result.success
    loop.fail(result.error)
    assert loop.state == State.FAILED


def test_phase1_retry_on_hal_failure():
    """RetryController retries HAL failures — transient faults are recovered."""
    world = WorldState(width=10, height=10)
    world.add_entity(Entity("agent1", EntityType.AGENT, 0, 0))

    call_count = {"n": 0}

    class FlakyActuator:
        def execute(self, command):
            from hal.types import CommandResult
            call_count["n"] += 1
            if call_count["n"] < 3:
                return CommandResult(
                    command_id=command.command_id,
                    success=False,
                    error="sensor glitch",
                )
            return CommandResult(command_id=command.command_id, success=True)

    flaky = FlakyActuator()
    registry = ToolRegistry()
    def move_tool(args: MoveArgs):
        r = flaky.execute(MoveCommand(agent_id="agent1", x=args.x, y=args.y))
        if not r.success:
            raise RuntimeError(r.error)
        return {"position": [args.x, args.y]}

    registry.register("move", MoveArgs, move_tool)
    retry = RetryController(
        registry,
        configs={"move": RetryConfig(max_retries=3, base_backoff=0.01)},
    )

    result = retry.dispatch(ToolCall("move", {"x": 1, "y": 1}))
    assert result.success
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_command_queue_with_hal():
    """CommandQueue drains commands to the actuator in priority order."""
    world = WorldState(width=10, height=10)
    world.add_entity(Entity("agent1", EntityType.AGENT, 0, 0))
    actuator = SimActuator(world)
    queue = CommandQueue()

    # enqueue out of priority order
    await queue.put(MoveCommand(agent_id="agent1", x=3, y=0), priority=10)
    await queue.put(MoveCommand(agent_id="agent1", x=1, y=0), priority=1)
    await queue.put(MoveCommand(agent_id="agent1", x=2, y=0), priority=5)

    # cancel the last one
    last = MoveCommand(agent_id="agent1", x=9, y=0)
    await queue.put(last, priority=1)
    queue.cancel(last.command_id)

    results = await queue.drain(actuator)

    # 3 executed (4th was cancelled), in priority order
    assert len(results) == 3
    assert all(r.success for r in results)
