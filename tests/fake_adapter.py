"""A GridWorld behind the adapter's HTTP contract, for tests. Every block and the bot sit at y = 64."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from breach.world import Action, GridWorld, Observation, Task

Y = 64


def observation(obs: Observation) -> dict[str, Any]:
    x, z = obs.position
    return {
        "server": obs.server, "position": {"x": x, "y": Y, "z": z}, "inventory": obs.inventory,
        "visible": [{"x": x, "y": Y, "z": z, "block": b} for x, z, b in obs.visible],
        "action_count": obs.action_count, "budget": obs.budget, "done": obs.done, "success": obs.success,
    }


def serve(make_world: Callable[[Task], GridWorld]) -> ThreadingHTTPServer:
    """Serves on a free port of 127.0.0.1 until shutdown(). Each POST /reset builds a fresh world for the posted task."""
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
            result = world.step(Action(body["action"], body.get("target"), body.get("grid")))
            return 200, {
                "ok": result.ok, "message": result.message, "output": result.output, "events": result.events,
                "observation": observation(result.observation),
            }

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # shutdown() waits up to one poll interval, 0.5 s by default.
    threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True).start()
    return httpd
