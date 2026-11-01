from pydantic import BaseModel
from agent.loop import AgentLoop, State
from agent.registry import ToolRegistry
from agent.types import ToolCall


# --- stub tool ---

class ScanArgs(BaseModel):
    radius: int

def scan_fn(args: ScanArgs) -> dict:
    return {"targets_found": args.radius * 2, "clear": args.radius < 5}


# --- wire it up ---

registry = ToolRegistry()
registry.register("scan", ScanArgs, scan_fn)

loop = AgentLoop(mission="scan the area with radius 3, then 5, then 10")

print(f"mission : {loop.mission}")
print(f"state   : {loop.state.name}\n")

# step through manually — this is what the agent loop will automate later

calls = [
    ToolCall("scan", {"radius": 3}),
    ToolCall("scan", {"radius": 5}),
    ToolCall("scan", {"radius": 10}),
]

for call in calls:
    loop.transition(State.PLANNING)
    print(f"[step {loop.step}] PLANNING → dispatching {call.tool_name}({call.args})")

    loop.transition(State.TOOL_CALL)
    result = registry.dispatch(call)

    loop.transition(State.WAITING)
    loop.transition(State.OBSERVING)

    if result.success:
        print(f"[step {loop.step}] OBSERVING → result: {result.output}")
    else:
        loop.fail(result.error)
        print(f"[step {loop.step}] FAILED → {loop.failure_reason}")
        break

if not loop.is_terminal():
    loop.transition(State.PLANNING)
    loop.transition(State.DONE)

print(f"\nfinal state : {loop.state.name}")
print(f"total steps : {loop.step}")
