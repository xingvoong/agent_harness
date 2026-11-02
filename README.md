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

## Phase 2 — Hardware Abstraction Layer + Simulation

### Summary

Phase 2 replaces stub tools with a real simulated environment. The agent now moves
through a 10x10 grid, picks up resources, and completes a mission with a win condition.
The HAL interface is the seam — swap `SimActuator` for real hardware without touching
agent code.

Four components:

- **WorldState** — 10x10 grid tracking entity positions, movement rules, and obstacle collision
- **Actuator / Sensor protocols** — stable interfaces; agent code only ever sees these, never the implementation
- **SimActuator + SimSensor** — concrete implementations backed by `WorldState`
- **CommandQueue** — async priority queue with cancellation by command ID

### Diagram

```
  keypress / agent decision
          │
          ▼
┌─────────────────────────────────────────────┐
│         Phase 1 Stack (unchanged)           │
│  AgentLoop → RetryController → ToolRegistry │
└────────────────────┬────────────────────────┘
                     │ tool fn raises on HAL failure
                     ▼
┌─────────────────────────────────────────────┐
│              Actuator / Sensor              │  ◄── stable interface
│         (Protocol — never changes)          │
└──────────┬──────────────────────┬───────────┘
           │                      │
    ┌──────▼──────┐        ┌──────▼──────┐
    │ SimActuator │        │  SimSensor  │
    │  move()     │        │  scan()     │
    │  pick_up()  │        │  observe()  │
    └──────┬──────┘        └──────┬──────┘
           │                      │
           └──────────┬───────────┘
                      ▼
         ┌────────────────────────┐
         │       WorldState       │
         │  grid · entities · tick│
         └────────────────────────┘

  CommandQueue (async, sits alongside)
  put(cmd, priority) → drain(actuator) → [CommandResult]
  cancel(command_id) drops command before execution
```

### How Phase 1 and Phase 2 connect

The bridge is the tool function. In Phase 1, tool functions returned stub data.
In Phase 2, they call into the HAL — and raise on failure so the RetryController
can retry and the loop can react.

```python
# Phase 1 stub (before)
def move_tool(args):
    return {"moved_to": [args.x, args.y]}

# Phase 2 HAL-backed (after)
def move_tool(args):
    result = actuator.execute(MoveCommand(agent_id="agent1", x=args.x, y=args.y))
    if not result.success:
        raise RuntimeError(result.error)   # RetryController sees this
    return {"position": [args.x, args.y]}
```

Everything above the tool function — `AgentLoop`, `RetryController`, `ToolRegistry`,
`ContextManager` — is unchanged. The HAL contract is what makes that possible.

### Key Takeaways

- **The HAL interface is the only stable contract.** `SimActuator` and `RealActuator`
  both implement `execute(command) → CommandResult`. Nothing above HAL imports from
  `sim/`. Swap the implementation, nothing breaks.

- **Tool functions are the bridge.** They translate between the agent's vocabulary
  (`ToolCall`) and the HAL's vocabulary (`Command`). They also own the failure
  translation — HAL returns `CommandResult(success=False)`, tool function raises,
  RetryController retries. Clean separation of concerns.

- **WorldState is the ground truth.** The sensor doesn't compute anything — it reads
  directly from world state. This means the agent's observations are always consistent
  with what actually happened.

### Interview Q&A

**Q: Why define `Actuator` and `Sensor` as protocols instead of base classes?**

Base classes force inheritance — every implementation must subclass `Actuator`.
Protocols use structural typing: any class with an `execute(command) → CommandResult`
method satisfies the contract, no import required. This means a `MockActuator` in
tests doesn't need to know about `hal/interfaces.py` at all. It also means real
hardware drivers written by a different team (or in a different language, via FFI)
satisfy the interface automatically as long as the method signature matches. The
contract is the shape, not the inheritance chain. For a HAL that needs to stay stable
across a long-lived project, that flexibility matters.

---

## Run

```bash
# set up
python3 -m venv .venv
.venv/bin/pip install pytest pydantic pytest-asyncio matplotlib

# interactive demo (Phase 1 + 2 wired together)
.venv/bin/python run_demo.py

# all tests
.venv/bin/pytest tests/ -v --asyncio-mode=auto
```

Demo controls: `arrow keys` / `wasd` to move · `p` to pick up · `s` to scan · `q` to quit

Collect all 3 resources then reach the objective to complete the mission.
