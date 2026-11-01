from agent.context import ContextManager, SUMMARY_MARKER
from agent.types import Message


def test_add_and_retrieve():
    ctx = ContextManager()
    ctx.add("system", "your mission is to scan the area")
    ctx.add("assistant", "scanning now")
    assert len(ctx.messages) == 2
    assert ctx.token_count > 0


def test_token_count_tracks_additions():
    ctx = ContextManager()
    ctx.add("user", "hello")
    count_after_one = ctx.token_count
    ctx.add("assistant", "world")
    assert ctx.token_count > count_after_one


def test_human_source_preserved():
    ctx = ContextManager()
    ctx.add("user", "obstacle cleared at 3,4", source="HUMAN")
    assert ctx.messages[-1].source == "HUMAN"


def test_no_summarize_below_threshold():
    ctx = ContextManager(token_budget=1000, summary_threshold=0.8)
    for i in range(5):
        ctx.add("assistant", f"step {i}")
    # well under 800 tokens — no summary should have fired
    assert not any(SUMMARY_MARKER in m.content for m in ctx.messages)


def test_summarize_fires_near_limit():
    # small budget so we hit the threshold quickly
    ctx = ContextManager(token_budget=40, summary_threshold=0.8)
    ctx.add("system", "mission: scan area")  # always kept
    for i in range(10):
        ctx.add("assistant", f"observation at step {i}: target acquired, moving forward")

    assert any(SUMMARY_MARKER in m.content for m in ctx.messages)


def test_head_and_tail_preserved_after_summary():
    ctx = ContextManager(token_budget=40, summary_threshold=0.8)
    ctx.add("system", "mission: scan area")
    for i in range(10):
        ctx.add("assistant", f"observation at step {i}: target acquired, moving forward")

    msgs = ctx.messages
    # first message is always the system/mission prompt
    assert msgs[0].content == "mission: scan area"
    # last 3 messages are the most recent
    assert "step 9" in msgs[-1].content
    assert "step 8" in msgs[-2].content
    assert "step 7" in msgs[-3].content


def test_message_count_reduced_after_summary():
    # 1 system + 10 assistant = 11 messages without summarization
    # after summarization: 1 head + 1 summary + 3 tail = 5 messages
    ctx = ContextManager(token_budget=40, summary_threshold=0.8)
    ctx.add("system", "mission: scan area")
    for i in range(10):
        ctx.add("assistant", f"observation at step {i}: target acquired, moving forward")

    assert len(ctx.messages) < 11
