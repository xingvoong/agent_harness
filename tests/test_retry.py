import time
import pytest
from pydantic import BaseModel
from agent.registry import ToolRegistry
from agent.retry import RetryController, RetryConfig
from agent.types import ToolCall


class PingArgs(BaseModel):
    pass


def make_controller(fn, config: RetryConfig | None = None) -> RetryController:
    r = ToolRegistry()
    r.register("ping", PingArgs, fn)
    configs = {"ping": config} if config else {}
    return RetryController(r, configs)


def test_succeeds_immediately():
    ctrl = make_controller(lambda _: "pong")
    result = ctrl.dispatch(ToolCall("ping", {}))
    assert result.success
    assert result.output == "pong"


def test_retries_then_succeeds():
    attempts = {"n": 0}

    def flaky(_):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("not ready")
        return "pong"

    ctrl = make_controller(flaky, RetryConfig(max_retries=3, base_backoff=0.01))
    result = ctrl.dispatch(ToolCall("ping", {}))
    assert result.success
    assert attempts["n"] == 3


def test_exhausts_retries():
    def always_fails(_):
        raise RuntimeError("dead")

    ctrl = make_controller(
        always_fails, RetryConfig(max_retries=2, base_backoff=0.01)
    )
    result = ctrl.dispatch(ToolCall("ping", {}))
    assert not result.success
    assert "dead" in result.error


def test_timeout():
    def slow(_):
        time.sleep(5)
        return "pong"

    ctrl = make_controller(
        slow, RetryConfig(max_retries=0, timeout_seconds=0.1)
    )
    result = ctrl.dispatch(ToolCall("ping", {}))
    assert not result.success
    assert result.error == "timeout"


def test_per_tool_config():
    attempts = {"n": 0}

    def flaky(_):
        attempts["n"] += 1
        raise RuntimeError("fail")

    r = ToolRegistry()
    r.register("ping", PingArgs, flaky)
    ctrl = RetryController(r, {"ping": RetryConfig(max_retries=1, base_backoff=0.01)})
    ctrl.dispatch(ToolCall("ping", {}))

    # max_retries=1 means 1 initial attempt + 1 retry = 2 total
    assert attempts["n"] == 2
