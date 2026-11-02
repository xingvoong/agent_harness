"""
Full stack demo — Phase 1 + Phase 2.

You control the agent. Every action runs through the full stack:
  keypress → ToolCall → RetryController → ToolRegistry → HAL → WorldState

Controls:
  arrow keys / wasd  — move agent
  p                  — pick up resource at current position
  s                  — scan surroundings (radius 3)
  q                  — quit

Left panel : the world grid
Right panel: agent loop state + context log
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pydantic import BaseModel

from sim.world import WorldState, Entity, EntityType
from hal.sim import SimActuator, SimSensor
from hal.types import MoveCommand, PickUpCommand, SensorQuery

from agent.loop import AgentLoop, State
from agent.registry import ToolRegistry
from agent.retry import RetryController
from agent.context import ContextManager
from agent.types import ToolCall


# ---------------------------------------------------------------------------
# Visuals
# ---------------------------------------------------------------------------

COLORS = {
    EntityType.AGENT:     "#4CAF50",
    EntityType.RESOURCE:  "#2196F3",
    EntityType.OBJECTIVE: "#FF9800",
    EntityType.OBSTACLE:  "#F44336",
}
MARKERS = {
    EntityType.AGENT:     "^",
    EntityType.RESOURCE:  "s",
    EntityType.OBJECTIVE: "*",
    EntityType.OBSTACLE:  "X",
}

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

class MoveArgs(BaseModel):
    x: int
    y: int

class PickUpArgs(BaseModel):
    resource_id: str

class ScanArgs(BaseModel):
    radius: int


# ---------------------------------------------------------------------------
# Build stack
# ---------------------------------------------------------------------------

world = WorldState(width=10, height=10)
world.add_entity(Entity("agent1", EntityType.AGENT,     0, 0))
world.add_entity(Entity("res1",   EntityType.RESOURCE,  2, 2))
world.add_entity(Entity("res2",   EntityType.RESOURCE,  1, 6))
world.add_entity(Entity("res3",   EntityType.RESOURCE,  8, 2))
world.add_entity(Entity("obj1",   EntityType.OBJECTIVE, 7, 7))
world.add_entity(Entity("wall1",  EntityType.OBSTACLE,  5, 5))
world.add_entity(Entity("wall2",  EntityType.OBSTACLE,  5, 4))
world.add_entity(Entity("wall3",  EntityType.OBSTACLE,  5, 6))
world.add_entity(Entity("wall4",  EntityType.OBSTACLE,  3, 8))
world.add_entity(Entity("wall5",  EntityType.OBSTACLE,  4, 8))

RESOURCES = {"res1", "res2", "res3"}

actuator = SimActuator(world)
sensor   = SimSensor(world)

def move_tool(args: MoveArgs):
    r = actuator.execute(MoveCommand(agent_id="agent1", x=args.x, y=args.y))
    if not r.success:
        raise RuntimeError(r.error)
    return {"position": [args.x, args.y]}

def pick_up_tool(args: PickUpArgs):
    r = actuator.execute(PickUpCommand(agent_id="agent1", resource_id=args.resource_id))
    if not r.success:
        raise RuntimeError(r.error)
    return {"picked_up": args.resource_id}

def scan_tool(args: ScanArgs):
    obs = sensor.read(SensorQuery(agent_id="agent1", radius=args.radius))
    return {
        "position": obs.position,
        "nearby": [{"id": e.id, "type": e.type, "x": e.x, "y": e.y} for e in obs.nearby],
        "tick": obs.tick,
    }

registry = ToolRegistry()
registry.register("move",    MoveArgs,   move_tool)
registry.register("pick_up", PickUpArgs, pick_up_tool)
registry.register("scan",    ScanArgs,   scan_tool)

retry = RetryController(registry)
ctx   = ContextManager(token_budget=2048)
loop  = AgentLoop(mission="collect res1, res2, res3 then reach obj1")
ctx.add("system", loop.mission)

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

log_lines = [f"mission: {loop.mission}", "─" * 36]

def render(ax_world, ax_log, status: str) -> None:
    # --- grid ---
    ax_world.cla()
    ax_world.set_xlim(-0.5, world.width - 0.5)
    ax_world.set_ylim(-0.5, world.height - 0.5)
    ax_world.set_xticks(range(world.width))
    ax_world.set_yticks(range(world.height))
    ax_world.grid(True, color="#e0e0e0", linewidth=0.5)
    ax_world.set_aspect("equal")
    ax_world.set_title(f"tick {world.tick}  |  state: {loop.state.name}", fontsize=10)

    for e in world.all():
        if e.held_by is not None:
            continue
        ax_world.plot(e.x, e.y, marker=MARKERS[e.type], color=COLORS[e.type], markersize=16)
        ax_world.annotate(e.id, (e.x, e.y), textcoords="offset points",
                          xytext=(5, 5), fontsize=7, color="#333")

    legend = [mpatches.Patch(color=COLORS[t], label=t.name) for t in EntityType]
    ax_world.legend(handles=legend, loc="upper right", fontsize=8)

    # --- log ---
    ax_log.cla()
    ax_log.axis("off")
    ax_log.set_title("context log", fontsize=10)
    visible = log_lines[-18:]
    ax_log.text(0.02, 0.98, "\n".join(visible),
                transform=ax_log.transAxes,
                fontsize=7.5, verticalalignment="top",
                fontfamily="monospace", color="#222",
                wrap=True)

    plt.suptitle(status, fontsize=9, color="#555")
    plt.tight_layout()
    plt.draw()


# ---------------------------------------------------------------------------
# Key handler
# ---------------------------------------------------------------------------

def dispatch(call: ToolCall) -> tuple[bool, str]:
    """Run a ToolCall through the full Phase 1 stack. Returns (success, msg)."""
    if loop.is_terminal():
        return False, "mission already terminated"

    loop.transition(State.PLANNING)
    loop.transition(State.TOOL_CALL)
    result = retry.dispatch(call)
    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)

    if result.success:
        ctx.add("user", f"[step {loop.step}] {call.tool_name} → {result.output}")
        log_lines.append(f"[{loop.step}] {call.tool_name}({call.args}) → ok")
        log_lines.append(f"     {result.output}")

        # check win condition after every successful move
        agent = world.get("agent1")
        at_objective = any(
            e.type == EntityType.OBJECTIVE
            for e in world.at(agent.x, agent.y)
        )
        all_collected = all(
            world.get(rid).held_by == "agent1" for rid in RESOURCES
        )
        if at_objective and all_collected:
            loop.transition(State.DONE)
            log_lines.append("─" * 36)
            log_lines.append("MISSION COMPLETE")
            return True, "MISSION COMPLETE — all resources collected!"
        elif at_objective and not all_collected:
            remaining = [rid for rid in RESOURCES if world.get(rid).held_by is None]
            return True, f"at objective — still need: {', '.join(remaining)}"

        return True, f"{call.tool_name} succeeded"
    else:
        # recoverable failure — stay in OBSERVING so the agent can try again
        ctx.add("user", f"[step {loop.step}] blocked: {result.error}")
        log_lines.append(f"[{loop.step}] blocked: {result.error}")
        return False, f"blocked: {result.error}"


def on_key(event) -> None:
    agent = world.get("agent1")
    x, y  = agent.x, agent.y
    status = "arrow/wasd=move  p=pick up  s=scan  q=quit"

    if event.key in ("up", "w"):
        ok, msg = dispatch(ToolCall("move", {"x": x, "y": y + 1}))
    elif event.key in ("down", "s") and event.key != "s":
        ok, msg = dispatch(ToolCall("move", {"x": x, "y": y - 1}))
    elif event.key == "down":
        ok, msg = dispatch(ToolCall("move", {"x": x, "y": y - 1}))
    elif event.key in ("left", "a"):
        ok, msg = dispatch(ToolCall("move", {"x": x - 1, "y": y}))
    elif event.key in ("right", "d"):
        ok, msg = dispatch(ToolCall("move", {"x": x + 1, "y": y}))
    elif event.key == "s":
        ok, msg = dispatch(ToolCall("scan", {"radius": 3}))
    elif event.key == "p":
        nearby = [e for e in world.at(x, y) if e.type == EntityType.RESOURCE]
        if nearby:
            ok, msg = dispatch(ToolCall("pick_up", {"resource_id": nearby[0].id}))
        else:
            msg = "no resource here"
            log_lines.append(f"  pick_up → nothing at ({x},{y})")
    elif event.key == "q":
        plt.close()
        return
    else:
        return

    if not loop.is_terminal():
        world.advance_tick()

    render(ax_world, ax_log, msg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

fig, (ax_world, ax_log) = plt.subplots(1, 2, figsize=(12, 6))
fig.canvas.mpl_connect("key_press_event", on_key)
render(ax_world, ax_log, "arrow/wasd=move  p=pick up  s=scan  q=quit")
plt.show()
