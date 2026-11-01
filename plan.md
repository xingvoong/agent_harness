# Agent Simulation Harness — Design Plan

## Purpose

A production-quality harness where an LLM agent receives a mission, executes tool calls,
and controls simulated hardware. Every design decision mirrors what you'd build for real
physical systems — with explicit safety boundaries, failure handling, and human override.

---

## High-Level System Diagram

```
  operator
     │  ▲
     │  │ pause / estop / inject observation
     ▼  │
┌─────────────────────────┐
│    OPERATOR INTERFACE   │  mission config, override commands
└────────────┬────────────┘
             │ mission start
             ▼
┌─────────────────────────┐
│      AGENT LOOP         │  IDLE → PLANNING → TOOL_CALL → WAITING → OBSERVING → DONE/FAILED
│  context │ tool registry│
└────────────┬────────────┘
             │ tool calls + observations
             ▼
┌─────────────────────────┐
│      SAFETY GATE        │  validate · rate limit · boundary check · kill switch
└────────────┬────────────┘
             │ validated commands
             ▼
┌─────────────────────────┐
│          HAL            │  Actuator + Sensor interfaces, Command Queue
└────────────┬────────────┘
             │ raw commands / sensor reads
             ▼
┌─────────────────────────┐
│      SIMULATION         │  world state, fault injector, scenario runner, replay
└────────────┬────────────┘
             │ all layers emit structured logs
             ▼
┌─────────────────────────┐
│     OBSERVABILITY       │  step traces, snapshots, replay engine
└─────────────────────────┘
```

---

## Layer Responsibilities

### Operator Interface
- Load mission config (YAML/JSON): objectives, constraints, time budget, allowed tools
- Human Override Console: pause, resume, emergency stop, inject corrective observation
- Read-only mission status feed

### Agent Execution Layer
**Agent Loop** — explicit state machine, never implicit:
- `IDLE` — waiting for mission
- `PLANNING` — LLM generates next action
- `TOOL_CALL` — dispatching to Safety Gate
- `WAITING` — pending async command result
- `OBSERVING` — processing environment feedback
- `DONE` / `FAILED` — terminal states with reason codes

**Context Manager** — tracks token budget, summarizes history when approaching limit,
preserves critical mission state across context resets.

**Tool Registry** — typed tool schemas (Pydantic), auto-validation, version-pinned.
No tool executes without passing schema check first.

**Retry/Timeout Controller** — per-tool configurable retries and deadlines.
Exponential backoff. Propagates failure reason to agent context.

### Safety Gate
Every command passes through before touching HAL. Non-negotiable.

- **Command Validator** — schema + semantic check (move distance within bounds, target entity exists)
- **Rate Limiter** — max N commands per second per tool type
- **Boundary Checker** — spatial and operational bounds from mission config
- **Kill Switch** — a single boolean flag checked before every command dispatch;
  can be flipped by operator or by automated circuit breaker

### Hardware Abstraction Layer (HAL)
The HAL contract: agent code never knows if it's talking to simulation or real hardware.
Swap the implementation, keep the interface.

- `Actuator.execute(command) → CommandResult`
- `Sensor.read(query) → ObservationModel`
- **Command Queue** — async priority queue; supports cancellation by command ID,
  deduplication of redundant moves

### Simulation Environment
- Grid world with typed entities (agent, obstacle, objective, resource)
- **Fault Injector** — configurable: drop commands, inject latency spikes, flip sensor readings
- **Scenario Runner** — loads scenario YAML, steps world forward, emits observations
- **Replay Engine** — stores full event log; can replay any mission from any step

### Observability
- Structured JSON log per step: `{step, state, tool, args, result, latency_ms, context_tokens}`
- State snapshots at configurable intervals
- Mission replay: given a log, re-run the mission deterministically

---

## Boundaries and Guardrails

### Hard Boundaries (enforced by Safety Gate, cannot be overridden by agent)
| Boundary | Enforcement |
|---|---|
| Spatial limits | Kill command if target coords exceed mission geofence |
| Command rate | Token bucket — burst allowed, sustained rate capped |
| Tool access | Agent can only call tools listed in mission config |
| Time budget | Mission auto-terminates at wall-clock deadline |
| Concurrent commands | Max 1 in-flight command per actuator at a time |

### Soft Boundaries (logged and flagged, agent can proceed)
| Boundary | Behavior |
|---|---|
| High context token usage | Warning injected into agent context |
| Repeated failed tool calls | Alert escalated to operator console |
| Low observation confidence | Flagged in ObservationModel, agent decides |

---

## Failure Handling

### Tool Call Failure
```
Tool call → timeout or error
    │
    ▼
RetryController: retry up to N times with backoff
    │
    ├─ success → continue
    └─ exhausted → inject TOOL_FAILURE observation into agent context
                   agent decides: retry differently, skip, or abort mission
```

### Agent Loop Stall
- Watchdog timer on each state transition
- If agent stays in `PLANNING` > T seconds: inject "time pressure" observation
- If agent stays in any state > hard deadline: force transition to `FAILED`

### Unrecoverable State
- Agent can emit `MISSION_ABORT` tool call — triggers clean shutdown
- Safety Gate detects command loop (same command issued 3x consecutively) → pause + operator alert

### Simulation Crash
- World state is snapshotted every K steps
- On crash: restore from last snapshot, replay missed steps
- If replay fails: mission marked FAILED with reason `SIM_CRASH`

---

## Shutdown Sequence

### Graceful Shutdown (operator-initiated or mission complete)
```
1. Stop issuing new tool calls (agent loop exits PLANNING → IDLE)
2. Wait for in-flight commands to complete or timeout (max 5s)
3. Cancel all pending queue entries
4. Flush observability logs to disk
5. Write final mission state snapshot
6. Emit MISSION_COMPLETE or MISSION_FAILED event
```

### Emergency Stop (operator kill switch or safety gate trigger)
```
1. Flip kill switch flag (checked before every command dispatch)
2. Cancel all in-flight and queued commands immediately
3. Freeze world state
4. Flush partial logs (best-effort)
5. Emit EMERGENCY_STOP event with last known state + reason
```

---

## Human Intervention

### When intervention triggers
- Operator manually hits pause/stop on console
- Safety Gate circuit breaker fires (rate exceeded, boundary violated, command loop detected)
- Agent emits `REQUEST_HUMAN_REVIEW` tool call (agent can ask for help)
- Watchdog escalates stall to operator

### What an operator can do
| Action | Effect |
|---|---|
| `PAUSE` | Agent loop stops at next state boundary, world frozen |
| `RESUME` | Agent loop restarts from last state |
| `EMERGENCY_STOP` | Full shutdown sequence (see above) |
| `INJECT_OBSERVATION` | Operator writes directly into agent context (e.g. "obstacle at 3,4 is now clear") |
| `OVERRIDE_COMMAND` | Operator issues a HAL command directly, bypassing agent |
| `RESET_MISSION` | Restore world to initial state, restart agent with same config |

### Operator injection protocol
Injected observations are tagged `source: HUMAN` in structured logs.
The agent sees them as normal observations — no special handling required.
This lets an operator course-correct without stopping the mission.

---

## Key Design Decisions

1. **Safety Gate is a separate layer, not agent logic.** The agent cannot bypass it.
   This is the only way to make safety guarantees when the agent is an LLM.

2. **HAL interface is the seam between soft and hard.** Everything above HAL is
   software-defined. Everything below HAL can be real hardware. The interface
   must stay stable — changing it breaks both sides.

3. **State machine is explicit, not emergent.** The agent loop has named states with
   named transitions. No "while True" with ad-hoc breaks. This makes replay,
   debugging, and operator intervention deterministic.

4. **Observability is a first-class layer, not logging.** Every step emits structured
   data. Replay is a design requirement, not a nice-to-have.

5. **Human intervention is an interface, not an escape hatch.** Operators interact
   through defined channels (pause, inject, override). No direct database writes,
   no process kills. This mirrors real operational safety requirements.

---

## Phases

---

### Phase 1 — Agent Loop + Tool Registry

**Goal:** A runnable agent loop that can call tools and transition through states.
No hardware, no simulation yet. Hardcode a stub tool that returns fake data.

**Build:**
- `AgentLoop` class with explicit state machine: `IDLE → PLANNING → TOOL_CALL → WAITING → OBSERVING → DONE/FAILED`
- `ToolRegistry` — register tools by name, validate args against Pydantic schema before dispatch
- `ContextManager` — track token count, summarize history when approaching limit
- `RetryController` — per-tool retry count and timeout config, exponential backoff

**Done when:** Agent can receive a mission string, call a stub tool 3 times with retries,
and terminate with a structured result.

**Interview surface:** State machine design, context window management, tool schema validation.

---

### Phase 2 — Hardware Abstraction Layer + Simulation

**Goal:** Replace the stub tool with a real simulated environment the agent can interact with.

**Build:**
- `Actuator` protocol: `execute(command: Command) → CommandResult`
- `Sensor` protocol: `read(query: SensorQuery) → ObservationModel`
- `SimActuator` and `SimSensor` — concrete implementations backed by world state
- `WorldState` — grid, entity positions, time tick, resource map
- `CommandQueue` — async priority queue with cancellation by command ID

**Done when:** Agent can navigate a 10x10 grid, pick up an object, and report success.
Swap `SimActuator` for a `MockActuator` in tests without changing agent code.

**Interview surface:** HAL interface stability, protocol/interface design, command queue concurrency.

---

### Phase 3 — Safety Gate

**Goal:** No command reaches HAL without passing safety checks. This layer is enforced
structurally — not by trusting the agent to behave.

**Build:**
- `CommandValidator` — schema + semantic check (target exists, distance valid)
- `RateLimiter` — token bucket per tool type, configurable burst and sustained rate
- `BoundaryChecker` — geofence from mission config, reject out-of-bounds commands
- `KillSwitch` — single boolean flag, checked before every dispatch; flippable by operator or circuit breaker
- `CircuitBreaker` — detects command loop (same command 3x in a row), pauses and alerts

**Done when:** Agent issues an out-of-bounds move → Safety Gate rejects it, injects
`BOUNDARY_VIOLATION` into agent context, agent re-plans. Kill switch stops execution mid-loop.

**Interview surface:** Why safety is a separate layer, circuit breaker design, rate limiting algorithms.

---

### Phase 4 — Scenario Runner + Fault Injector

**Goal:** Repeatable, configurable test runs. Inject failures to test agent resilience.

**Build:**
- `ScenarioRunner` — loads scenario YAML (objectives, time budget, allowed tools, geofence),
  steps world forward, emits observations on schedule
- `FaultInjector` — plugs into HAL layer; configurable: drop N% of commands, add latency spike,
  flip sensor reading to wrong value
- `WorldSnapshot` — serialize/restore full world state; snapshot every K steps

**Done when:** Run the same scenario 10 times with different fault rates, get consistent
DONE/FAILED outcomes. Restore from snapshot after a simulated crash.

**Interview surface:** Simulation fidelity tradeoffs, fault injection design, snapshot/restore for reliability.

---

### Phase 5 — Observability + Replay Engine

**Goal:** Every step is recorded. Any mission can be replayed from any point.

**Build:**
- `StepLogger` — emits structured JSON per step:
  `{step, timestamp, state, tool, args, result, latency_ms, context_tokens, source}`
- `MissionTrace` — append-only log stored to disk; one file per mission run
- `ReplayEngine` — given a trace file and a step number, restore world state and re-run
  from that point; deterministic given same seed
- Tag all operator-injected observations as `source: HUMAN` vs `source: AGENT`

**Done when:** Run a mission, introduce a bug mid-way, replay from step before the bug,
confirm identical behavior. Step through a trace and inspect state at each tick.

**Interview surface:** Observability as a design requirement, deterministic replay, structured logging schema.

---

### Phase 6 — Operator Console (CLI)

**Goal:** A human can monitor, pause, intervene, and stop a running mission from a terminal.

**Build:**
- Live status feed: current state, last tool call, step count, context token usage
- Commands:
  - `pause` / `resume` — stops agent loop at next state boundary
  - `stop` — graceful shutdown sequence
  - `estop` — emergency stop, immediate
  - `inject "<observation text>"` — write observation into agent context, tagged `source: HUMAN`
  - `override <tool> <args>` — issue HAL command directly, bypassing agent
  - `reset` — restore to initial world state, restart agent

**Done when:** Operator can pause a running mission, inject a corrective observation,
resume, and see the agent incorporate the new information in its next planning step.

**Interview surface:** Human-in-the-loop interface design, why intervention is a protocol not an escape hatch,
operational safety requirements for physical systems.
