import time
import concurrent.futures
from dataclasses import dataclass, field
from agent.registry import ToolRegistry
from agent.types import ToolCall, ToolResult


@dataclass
class RetryConfig:
    max_retries: int = 3
    timeout_seconds: float = 5.0
    base_backoff: float = 0.5  # doubles each attempt: 0.5s, 1s, 2s, ...


class RetryController:
    def __init__(
        self,
        registry: ToolRegistry,
        configs: dict[str, RetryConfig] | None = None,
    ) -> None:
        self._registry = registry
        self._configs: dict[str, RetryConfig] = configs or {}
        self._default = RetryConfig()

    def dispatch(self, call: ToolCall) -> ToolResult:
        config = self._configs.get(call.tool_name, self._default)
        result: ToolResult | None = None

        for attempt in range(config.max_retries + 1):
            result = self._run_with_timeout(call, config.timeout_seconds)

            if result.success:
                return result

            if attempt < config.max_retries:
                backoff = config.base_backoff * (2 ** attempt)
                time.sleep(backoff)

        return result  # last failed result

    def _run_with_timeout(self, call: ToolCall, timeout: float) -> ToolResult:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._registry.dispatch, call)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                return ToolResult(
                    tool_name=call.tool_name,
                    success=False,
                    output=None,
                    error="timeout",
                )
