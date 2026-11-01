import pytest
from agent.loop import AgentLoop, State


def test_initial_state():
    loop = AgentLoop(mission="test mission")
    assert loop.state == State.IDLE
    assert loop.step == 0


def test_valid_transitions():
    loop = AgentLoop(mission="test")
    loop.transition(State.PLANNING)
    assert loop.state == State.PLANNING
    assert loop.step == 1

    loop.transition(State.TOOL_CALL)
    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)
    loop.transition(State.PLANNING)
    loop.transition(State.DONE)
    assert loop.state == State.DONE
    assert loop.is_terminal()


def test_invalid_transition_raises():
    loop = AgentLoop(mission="test")
    with pytest.raises(ValueError, match="Invalid transition"):
        loop.transition(State.DONE)  # can't jump from IDLE to DONE


def test_fail_sets_reason():
    loop = AgentLoop(mission="test")
    loop.transition(State.PLANNING)
    loop.fail("tool timeout")
    assert loop.state == State.FAILED
    assert loop.failure_reason == "tool timeout"
    assert loop.is_terminal()


def test_no_exit_from_terminal():
    loop = AgentLoop(mission="test")
    loop.transition(State.PLANNING)
    loop.transition(State.DONE)
    with pytest.raises(ValueError):
        loop.transition(State.PLANNING)
