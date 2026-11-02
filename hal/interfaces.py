from typing import Protocol
from hal.types import Command, CommandResult, SensorQuery, ObservationModel


class Actuator(Protocol):
    def execute(self, command: Command) -> CommandResult: ...


class Sensor(Protocol):
    def read(self, query: SensorQuery) -> ObservationModel: ...
