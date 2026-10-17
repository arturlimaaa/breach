"""A GridWorld behind the adapter's HTTP contract, for tests. Every block and the bot sit at y = 64."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from breach.world import DIRECTIONS, HEADINGS, RADIUS, Action, GridWorld, Observation, Position, StepResult, Task, within

Y = 64


def observation(obs: Observation) -> dict[str, Any]:
    x, z = obs.position
    return {
        "server": obs.server, "position": {"x": x, "y": Y, "z": z}, "inventory": obs.inventory,
        "visible": [{"x": x, "y": Y, "z": z, "block": b} for x, z, b in obs.visible],
        "action_count": obs.action_count, "budget": obs.budget, "done": obs.done, "success": obs.success,
    }


def step(world: GridWorld, action: Action) -> StepResult:
    """One adapter step on the grid. The adapter's pathing takes one action each: `move {"toward": b}` stops next to the
    nearest b in view, `move {"heading": h, "blocks": n}` goes up to n cells along h, and `mine b` steps onto the nearest b
    within reach 1, where the grid mines.

    The adapter's mine walks to any b in sight; reach 1 is stricter so that a test proves the executor travelled first."""
    if not world.done and action.name == "move" and isinstance(action.target, dict) and "heading" in action.target:
        return heading_move(world, action.target["heading"], action.target["blocks"])
    toward = action.name == "move" and isinstance(action.target, dict)
    if world.done or not (toward or action.name == "mine" and action.target):
        return world.step(action)
    block, reach = (action.target["toward"], RADIUS) if toward else (action.target, 1)
    x0, z0 = world.position

    def away(p: Position) -> int:
        return abs(p[0] - x0) + abs(p[1] - z0)

    cell = min((p for p, b in world.blocks.items() if b == block and away(p) <= reach), key=lambda p: (away(p), p), default=None)
    if cell is not None and not toward:
        world.position = cell
        return world.step(action)
    world.actions += 1
    if cell is None:
        return StepResult(False, f"no {block} within {reach} blocks", None, world.observe(), executed=False)
    world.position = min(((cell[0] + dx, cell[1] + dz) for dx, dz in DIRECTIONS.values()), key=away)
    return StepResult(True, f"moved toward {block}", None, world.observe())


def heading_move(world: GridWorld, heading: str, blocks: int) -> StepResult:
    """The adapter's heading move as a teleport that stops short of the first block on the way; ok when it ends within one
    cell of the point `blocks` along `heading`."""
    (dx, dz), (x0, z0) = HEADINGS[heading], world.position
    walked = next((k - 1 for k in range(1, blocks + 1) if (x0 + k * dx, z0 + k * dz) in world.blocks), blocks)
    world.position = (x0 + walked * dx, z0 + walked * dz)
    world.actions += 1
    ok = within(world.position, (x0 + blocks * dx, z0 + blocks * dz))
    return StepResult(ok, f"moved {walked} of {blocks} blocks {heading}", None, world.observe())


def serve(make_world: Callable[[Task], GridWorld], on_step: Callable[[dict[str, Any]], None] = lambda body: None) -> ThreadingHTTPServer:
    """Serves on a free port of 127.0.0.1 until shutdown(). Each POST /reset builds a fresh world for the posted task.

    `on_step` sees every POST /step body as sent."""
    world: GridWorld | None = None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, payload = self.respond()
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def respond(self) -> tuple[int, dict[str, Any]]:
            nonlocal world
            route = f"{self.command} {self.path}"
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or "{}")
            if route == "POST /reset":
                world = make_world(Task(**body["task"]))
                gives = [f"/give @s {item} {n}" for item, n in world.task.inventory.items()]
                return 200, observation(world.observe()) | {"message": "; ".join(["/clear", *gives])}
            if route not in ("GET /observe", "POST /step"):
                return 404, {"error": f"no route {route}"}
            if world is None:
                return 409, {"error": "POST /reset first"}
            if route == "GET /observe":
                return 200, observation(world.observe())
            on_step(body)
            result = step(world, Action(body["action"], body.get("target"), body.get("grid")))
            return 200, {
                "ok": result.ok, "message": result.message, "output": result.output, "events": result.events,
                "executed": result.executed, "observation": observation(result.observation),
            }

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # shutdown() waits up to one poll interval, 0.5 s by default.
    threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True).start()
    return httpd
