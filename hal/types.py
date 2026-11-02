from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import uuid


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# Commands (agent → actuator)
# ---------------------------------------------------------------------------

@dataclass
class Command:
    agent_id: str
    command_id: str = field(default_factory=_new_id)


@dataclass
class MoveCommand(Command):
    x: int = 0
    y: int = 0


@dataclass
class PickUpCommand(Command):
    resource_id: str = ""


@dataclass
class CommandResult:
    command_id: str
    success: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Sensor queries (agent → sensor)
# ---------------------------------------------------------------------------

@dataclass
class SensorQuery:
    agent_id: str
    radius: int = 3          # how far to scan for nearby entities


@dataclass
class NearbyEntity:
    id: str
    type: str
    x: int
    y: int
    held_by: Optional[str] = None


@dataclass
class ObservationModel:
    agent_id: str
    position: tuple[int, int]
    nearby: list[NearbyEntity]
    tick: int
    metadata: dict[str, Any] = field(default_factory=dict)
