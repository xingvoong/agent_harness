from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class EntityType(Enum):
    AGENT = auto()
    OBSTACLE = auto()
    OBJECTIVE = auto()
    RESOURCE = auto()


@dataclass
class Entity:
    id: str
    type: EntityType
    x: int
    y: int
    held_by: Optional[str] = None  # agent id if picked up


@dataclass
class WorldState:
    width: int
    height: int
    tick: int = field(default=0, init=False)
    _entities: dict[str, Entity] = field(default_factory=dict, init=False)

    def add_entity(self, entity: Entity) -> None:
        if not self._in_bounds(entity.x, entity.y):
            raise ValueError(f"Position ({entity.x},{entity.y}) out of bounds")
        self._entities[entity.id] = entity

    def get(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def all(self) -> list[Entity]:
        return list(self._entities.values())

    def at(self, x: int, y: int) -> list[Entity]:
        return [e for e in self._entities.values() if e.x == x and e.y == y]

    def move(self, entity_id: str, x: int, y: int) -> None:
        entity = self._require(entity_id)
        if not self._in_bounds(x, y):
            raise ValueError(f"Position ({x},{y}) out of bounds")
        if any(e.type == EntityType.OBSTACLE for e in self.at(x, y)):
            raise ValueError(f"Obstacle at ({x},{y})")
        entity.x = x
        entity.y = y

    def pick_up(self, agent_id: str, resource_id: str) -> None:
        agent = self._require(agent_id)
        resource = self._require(resource_id)
        if resource.type != EntityType.RESOURCE:
            raise ValueError(f"{resource_id} is not a resource")
        if resource.x != agent.x or resource.y != agent.y:
            raise ValueError("Agent not at resource location")
        resource.held_by = agent_id

    def advance_tick(self) -> None:
        self.tick += 1

    # --- internal ---

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def _require(self, entity_id: str) -> Entity:
        entity = self._entities.get(entity_id)
        if entity is None:
            raise ValueError(f"Unknown entity: {entity_id}")
        return entity
