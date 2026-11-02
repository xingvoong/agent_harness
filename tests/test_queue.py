import pytest
import pytest_asyncio
from sim.world import WorldState, Entity, EntityType
from hal.sim import SimActuator
from hal.queue import CommandQueue
from hal.types import MoveCommand, PickUpCommand


pytestmark = pytest.mark.asyncio


def make_actuator() -> SimActuator:
    world = WorldState(width=10, height=10)
    world.add_entity(Entity("agent1", EntityType.AGENT, 0, 0))
    world.add_entity(Entity("res1", EntityType.RESOURCE, 3, 3))
    return SimActuator(world)


async def test_single_command_executes():
    q = CommandQueue()
    actuator = make_actuator()
    await q.put(MoveCommand(agent_id="agent1", x=1, y=1))
    results = await q.drain(actuator)
    assert len(results) == 1
    assert results[0].success


async def test_priority_order():
    """Lower priority number executes first."""
    q = CommandQueue()
    order = []

    class TrackingActuator:
        def execute(self, command):
            from hal.types import CommandResult
            order.append(command.x)
            return CommandResult(command_id=command.command_id, success=True)

    actuator = TrackingActuator()
    await q.put(MoveCommand(agent_id="a", x=3, y=0), priority=10)
    await q.put(MoveCommand(agent_id="a", x=1, y=0), priority=1)
    await q.put(MoveCommand(agent_id="a", x=2, y=0), priority=5)

    await q.drain(actuator)
    assert order == [1, 2, 3]


async def test_fifo_within_same_priority():
    q = CommandQueue()
    order = []

    class TrackingActuator:
        def execute(self, command):
            from hal.types import CommandResult
            order.append(command.x)
            return CommandResult(command_id=command.command_id, success=True)

    actuator = TrackingActuator()
    for x in [1, 2, 3]:
        await q.put(MoveCommand(agent_id="a", x=x, y=0), priority=5)

    await q.drain(actuator)
    assert order == [1, 2, 3]


async def test_cancel_drops_command():
    q = CommandQueue()
    actuator = make_actuator()

    cmd = MoveCommand(agent_id="agent1", x=1, y=1)
    await q.put(cmd)
    q.cancel(cmd.command_id)

    results = await q.drain(actuator)
    assert results == []


async def test_cancel_only_targets_one_command():
    q = CommandQueue()
    actuator = make_actuator()

    cmd1 = MoveCommand(agent_id="agent1", x=1, y=1)
    cmd2 = MoveCommand(agent_id="agent1", x=2, y=2)
    await q.put(cmd1)
    await q.put(cmd2)
    q.cancel(cmd1.command_id)

    results = await q.drain(actuator)
    assert len(results) == 1
    assert results[0].success


async def test_empty_queue_drains_cleanly():
    q = CommandQueue()
    actuator = make_actuator()
    results = await q.drain(actuator)
    assert results == []


async def test_size_and_empty():
    q = CommandQueue()
    assert q.empty()
    assert q.size() == 0

    await q.put(MoveCommand(agent_id="agent1", x=1, y=1))
    assert not q.empty()
    assert q.size() == 1
