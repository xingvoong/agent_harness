from sim.world import WorldState, Entity, EntityType
from hal.sim import SimActuator, SimSensor
from hal.types import MoveCommand, PickUpCommand, SensorQuery


def make_world() -> WorldState:
    w = WorldState(width=10, height=10)
    w.add_entity(Entity("agent1", EntityType.AGENT, 0, 0))
    w.add_entity(Entity("res1", EntityType.RESOURCE, 2, 2))
    w.add_entity(Entity("wall1", EntityType.OBSTACLE, 5, 5))
    return w


# --- actuator ---

def test_move_success():
    world = make_world()
    actuator = SimActuator(world)
    result = actuator.execute(MoveCommand(agent_id="agent1", x=3, y=3))
    assert result.success
    assert world.get("agent1").x == 3


def test_move_into_obstacle_fails():
    world = make_world()
    actuator = SimActuator(world)
    result = actuator.execute(MoveCommand(agent_id="agent1", x=5, y=5))
    assert not result.success
    assert "Obstacle" in result.error


def test_move_out_of_bounds_fails():
    world = make_world()
    actuator = SimActuator(world)
    result = actuator.execute(MoveCommand(agent_id="agent1", x=99, y=99))
    assert not result.success
    assert "out of bounds" in result.error


def test_pick_up_success():
    world = make_world()
    actuator = SimActuator(world)
    actuator.execute(MoveCommand(agent_id="agent1", x=2, y=2))
    result = actuator.execute(PickUpCommand(agent_id="agent1", resource_id="res1"))
    assert result.success
    assert world.get("res1").held_by == "agent1"


def test_pick_up_wrong_position_fails():
    world = make_world()
    actuator = SimActuator(world)
    result = actuator.execute(PickUpCommand(agent_id="agent1", resource_id="res1"))
    assert not result.success


# --- sensor ---

def test_sensor_returns_position():
    world = make_world()
    sensor = SimSensor(world)
    obs = sensor.read(SensorQuery(agent_id="agent1", radius=5))
    assert obs.position == (0, 0)
    assert obs.tick == 0


def test_sensor_detects_nearby():
    world = make_world()
    sensor = SimSensor(world)
    obs = sensor.read(SensorQuery(agent_id="agent1", radius=5))
    ids = [e.id for e in obs.nearby]
    assert "res1" in ids
    assert "wall1" in ids


def test_sensor_radius_filters_far_entities():
    world = make_world()
    sensor = SimSensor(world)
    # radius 1 from (0,0) — res1 at (2,2) is outside
    obs = sensor.read(SensorQuery(agent_id="agent1", radius=1))
    ids = [e.id for e in obs.nearby]
    assert "res1" not in ids


def test_sensor_unknown_agent():
    world = make_world()
    sensor = SimSensor(world)
    obs = sensor.read(SensorQuery(agent_id="ghost", radius=3))
    assert obs.position == (-1, -1)
    assert "error" in obs.metadata


# --- swap test: MockActuator satisfies the same interface ---

class MockActuator:
    """Minimal mock — accepts any command, always succeeds."""
    def execute(self, command) -> object:
        from hal.types import CommandResult
        return CommandResult(command_id=command.command_id, success=True)


def test_mock_actuator_satisfies_interface():
    mock = MockActuator()
    result = mock.execute(MoveCommand(agent_id="agent1", x=1, y=1))
    assert result.success
