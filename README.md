# Agent Simulation Harness

A production-quality harness where an LLM agent receives a mission, executes tool calls,
and controls simulated hardware. Every design decision mirrors what you'd build for real
physical systems — with explicit safety boundaries, failure handling, and human override.

Full design: [plan.md](plan.md)

---

## Phase 1 — Agent Loop + Tool Registry

### Summary

Builds the core execution engine: the agent receives a mission, plans actions, calls tools,
observes results, and terminates. No hardware, no LLM yet — just the skeleton that every
other phase plugs into.

Four components, each with a single responsibility:

- **AgentLoop** — enforces state transitions; the agent can only move through defined paths
- **ToolRegistry** — validates tool args before dispatch; bad input never reaches a tool function
- **RetryController** — wraps dispatch with per-tool retry, timeout, and exponential backoff
- **ContextManager** — tracks token usage and compresses history when approaching the limit

### Diagram

```
  mission string
       │
       ▼
┌─────────────────────────────────────────────┐
│                 AgentLoop                   │
│                                             │
│  IDLE ──► PLANNING ──► TOOL_CALL ──► WAITING│
│    ▲                                   │    │
│    │          DONE / FAILED ◄── OBSERVING   │
└────────────────────┬────────────────────────┘
                     │ ToolCall
                     ▼
┌─────────────────────────────────────────────┐
│              RetryController                │
│  attempt → backoff → retry (up to N times)  │
│  timeout per attempt via ThreadPoolExecutor │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│              ToolRegistry                   │
│  validate args (Pydantic) → call fn         │
│  unknown tool / bad args → ToolResult(fail) │
└────────────────────┬────────────────────────┘
                     │ ToolResult
                     ▼
┌─────────────────────────────────────────────┐
│             ContextManager                  │
│  append message → track tokens              │
│  near limit → compress middle, keep head+tail│
└─────────────────────────────────────────────┘
```

Each layer returns a clean result — no exceptions propagate across boundaries.

### Key Takeaways

- **State machine is explicit, not emergent.** Transitions are a lookup table. An invalid
  move raises immediately rather than leaving the agent in an undefined state. This makes
  replay and debugging deterministic.

- **Validation happens at the boundary.** The registry rejects bad args before the tool
  function ever runs. The agent gets a `ToolResult(success=False)` back — not a traceback.

- **Failures are data, not exceptions.** Every failure path returns a structured result
  with a reason. The loop decides what to do with it — retry, re-plan, or abort.

- **Context compression is deterministic.** No LLM needed to summarize. Keep head (mission)
  + last 3 messages, compress middle into a single marker. Swappable for real summarization
  later without changing the interface.

### Interview Q&A

**Q: Why use an explicit state machine instead of a simple while loop?**

A while loop with conditionals works until something goes wrong — then you don't know
what state the agent was in when it failed. An explicit state machine gives you three
things: invalid transitions raise immediately (no silent drift), every state is named
and loggable, and human intervention has a defined place to hook in (pause at the next
state boundary). When you're operating a physical system, knowing exactly what the agent
was doing at failure isn't optional.

---

**Q: Why does the RetryController run each attempt in a thread?**

The tool function is synchronous. To enforce a per-attempt timeout without blocking the
main thread indefinitely, we submit the call to a `ThreadPoolExecutor` and call
`future.result(timeout=N)`. If it stalls, we get a `TimeoutError` back and return a
clean `ToolResult(error="timeout")` — the agent loop never sees an exception. The
alternative (asyncio) requires the tool functions to be async, which is a bigger contract
to enforce. Threads keep the tool interface simple: any callable works.

---

## Run Phase 1

```bash
# set up
python3 -m venv .venv
.venv/bin/pip install pytest pydantic

# run the demo
.venv/bin/python run_demo.py

# run all tests
.venv/bin/pytest tests/ -v
```
