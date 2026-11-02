import asyncio
import itertools
from hal.types import Command, CommandResult
from hal.interfaces import Actuator


class CommandQueue:
    """
    Async priority queue with cancellation.

    Lower priority number = executes first (0 is highest priority).
    Within the same priority, FIFO order is preserved.
    Cancelled commands are dropped silently when dequeued.
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._cancelled: set[str] = set()
        self._counter = itertools.count()   # tiebreaker for same-priority items

    async def put(self, command: Command, priority: int = 5) -> None:
        seq = next(self._counter)
        await self._queue.put((priority, seq, command))

    def cancel(self, command_id: str) -> None:
        self._cancelled.add(command_id)

    async def get(self) -> Command:
        """Block until a non-cancelled command is available."""
        while True:
            _, _, command = await self._queue.get()
            if command.command_id in self._cancelled:
                self._cancelled.discard(command.command_id)
                self._queue.task_done()
                continue
            return command

    async def drain(self, actuator: Actuator) -> list[CommandResult]:
        """Execute all queued commands in priority order. Returns results."""
        results = []
        while not self._queue.empty():
            try:
                _, _, command = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            if command.command_id in self._cancelled:
                self._cancelled.discard(command.command_id)
                continue
            result = actuator.execute(command)
            results.append(result)
        return results

    def empty(self) -> bool:
        return self._queue.empty()

    def size(self) -> int:
        return self._queue.qsize()
