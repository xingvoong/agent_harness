from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class State(Enum):
    IDLE = auto()
    PLANNING = auto()
    TOOL_CALL = auto()
    WAITING = auto()
    OBSERVING = auto()
    DONE = auto()
    FAILED = auto()


TERMINAL_STATES = {State.DONE, State.FAILED}

# Valid transitions: state -> set of states it can move to
TRANSITIONS: dict[State, set[State]] = {
    State.IDLE:      {State.PLANNING},
    State.PLANNING:  {State.TOOL_CALL, State.DONE, State.FAILED},
    State.TOOL_CALL: {State.WAITING, State.FAILED},
    State.WAITING:   {State.OBSERVING, State.FAILED},
    State.OBSERVING: {State.PLANNING, State.DONE, State.FAILED},
    State.DONE:      set(),
    State.FAILED:    set(),
}


@dataclass
class AgentLoop:
    mission: str
    state: State = field(default=State.IDLE, init=False)
    step: int = field(default=0, init=False)
    failure_reason: Optional[str] = field(default=None, init=False)

    def transition(self, next_state: State) -> None:
        allowed = TRANSITIONS[self.state]
        if next_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self.state.name} -> {next_state.name}"
            )
        self.state = next_state
        self.step += 1

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def fail(self, reason: str) -> None:
        self.failure_reason = reason
        self.transition(State.FAILED)
