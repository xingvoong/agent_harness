from hal.types import (
    Command, CommandResult, MoveCommand, PickUpCommand,
    SensorQuery, ObservationModel, NearbyEntity,
)
from sim.world import WorldState


class SimActuator:
    def __init__(self, world: WorldState) -> None:
        self._world = world

    def execute(self, command: Command) -> CommandResult:
        try:
            if isinstance(command, MoveCommand):
                self._world.move(command.agent_id, command.x, command.y)
            elif isinstance(command, PickUpCommand):
                self._world.pick_up(command.agent_id, command.resource_id)
            else:
                return CommandResult(
                    command_id=command.command_id,
                    success=False,
                    error=f"unknown command type: {type(command).__name__}",
                )
            return CommandResult(command_id=command.command_id, success=True)
        except ValueError as e:
            return CommandResult(
                command_id=command.command_id,
                success=False,
                error=str(e),
            )


class SimSensor:
    def __init__(self, world: WorldState) -> None:
        self._world = world

    def read(self, query: SensorQuery) -> ObservationModel:
        agent = self._world.get(query.agent_id)
        if agent is None:
            return ObservationModel(
                agent_id=query.agent_id,
                position=(-1, -1),
                nearby=[],
                tick=self._world.tick,
                metadata={"error": f"unknown agent: {query.agent_id}"},
            )

        nearby = [
            NearbyEntity(
                id=e.id,
                type=e.type.name,
                x=e.x,
                y=e.y,
                held_by=e.held_by,
            )
            for e in self._world.all()
            if e.id != query.agent_id
            and abs(e.x - agent.x) <= query.radius
            and abs(e.y - agent.y) <= query.radius
        ]

        return ObservationModel(
            agent_id=query.agent_id,
            position=(agent.x, agent.y),
            nearby=nearby,
            tick=self._world.tick,
        )
