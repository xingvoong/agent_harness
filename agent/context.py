from agent.types import Message, _estimate_tokens


SUMMARY_MARKER = "[SUMMARIZED]"


class ContextManager:
    def __init__(
        self,
        token_budget: int = 4096,
        summary_threshold: float = 0.8,
    ) -> None:
        self._budget = token_budget
        self._threshold = summary_threshold
        self._messages: list[Message] = []
        self._total_tokens: int = 0

    # --- public interface ---

    def add(self, role: str, content: str, source: str = "AGENT") -> None:
        msg = Message(role=role, content=content, source=source)
        self._messages.append(msg)
        self._total_tokens += msg.token_count

        if self._near_limit():
            self._summarize()

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    @property
    def token_count(self) -> int:
        return self._total_tokens

    @property
    def token_budget(self) -> int:
        return self._budget

    def near_limit(self) -> bool:
        return self._near_limit()

    # --- summarization ---

    def _near_limit(self) -> bool:
        return self._total_tokens >= self._budget * self._threshold

    def _summarize(self) -> None:
        # Always keep: first message (mission/system prompt) + last 3 messages
        # Compress everything in between into a single summary message
        if len(self._messages) <= 4:
            return

        keep_head = self._messages[:1]
        keep_tail = self._messages[-3:]
        middle = self._messages[1:-3]

        if not middle:
            return

        summary_text = self._compress(middle)
        summary_msg = Message(role="system", content=summary_text, source="AGENT")

        self._messages = keep_head + [summary_msg] + keep_tail
        self._total_tokens = sum(m.token_count for m in self._messages)

    def _compress(self, messages: list[Message]) -> str:
        # Deterministic compression — no LLM needed yet.
        # Extracts tool calls and results from middle messages.
        lines = [f"{SUMMARY_MARKER} Prior context condensed:"]
        for msg in messages:
            first_line = msg.content.splitlines()[0][:120]
            lines.append(f"  [{msg.role}] {first_line}")
        return "\n".join(lines)
