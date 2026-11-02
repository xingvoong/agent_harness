import pytest
from sim.world import WorldState, Entity, EntityType


def make_world() -> WorldState:
    w = WorldState(width=10, height=10)
    w.add_entity(Entity("agent1", EntityType.AGENT, 0, 0))
    w.add_entity(Entity("res1", EntityType.RESOURCE, 2, 2))
    w.add_entity(Entity("wall1", EntityType.OBSTACLE, 5, 5))
    return w


def test_move_agent():
    w = make_world()
    w.move("agent1", 3, 3)
    assert w.get("agent1").x == 3
    assert w.get("agent1").y == 3


def test_move_out_of_bounds():
    w = make_world()
    with pytest.raises(ValueError, match="out of bounds"):
        w.move("agent1", 10, 10)


def test_move_into_obstacle():
    w = make_world()
    with pytest.raises(ValueError, match="Obstacle"):
        w.move("agent1", 5, 5)


def test_pick_up_resource():
    w = make_world()
    w.move("agent1", 2, 2)
    w.pick_up("agent1", "res1")
    assert w.get("res1").held_by == "agent1"


def test_pick_up_from_wrong_position():
    w = make_world()  # agent at 0,0 resource at 2,2
    with pytest.raises(ValueError, match="not at resource"):
        w.pick_up("agent1", "res1")


def test_at_returns_entities_at_position():
    w = make_world()
    entities = w.at(2, 2)
    assert any(e.id == "res1" for e in entities)


def test_tick_advances():
    w = make_world()
    w.advance_tick()
    w.advance_tick()
    assert w.tick == 2
