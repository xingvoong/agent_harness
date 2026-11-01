from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class ToolCall:
    tool_name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = field(default=None)


@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str
    source: Literal["AGENT", "HUMAN"] = "AGENT"
    token_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.token_count = _estimate_tokens(self.content)


def _estimate_tokens(text: str) -> int:
    # ~4 chars per token — good enough until we wire a real tokenizer
    return max(1, len(text) // 4)
