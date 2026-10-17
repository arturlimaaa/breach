"""GridWorld's interface over the Node adapter's local HTTP contract (docs/design.md, "Adapter contract")."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .world import RADIUS, Action, Observation, Position, StepResult, Task

TIMEOUT = 90  # seconds; the adapter bounds a step at 60 s and serves one request at a time


def parse(data: dict[str, Any]) -> Observation:
    """An adapter observation on the core's (x, z) plane. Each column keeps the visible block whose y is nearest the bot."""
    x, y, z = (data["position"][k] for k in "xyz")
    # Farthest y first, so the nearest one is written last.
    columns = {(v["x"], v["z"]): v["block"] for v in sorted(data["visible"], key=lambda v: -abs(v["y"] - y))}
    return Observation(
        data["server"], (x, z), dict(data["inventory"]), [(*p, b) for p, b in columns.items()],
        data["action_count"], data["budget"], data["done"], data["success"],
    )


class HttpWorld:
    """The adapter behind the world interface the executor and B use. Every observation refreshes the attributes."""

    def __init__(self, base_url: str, task: Task, server: str | None = None):
        """POST /reset with `task`. `server` relabels the adapter's server, which is the rule scope."""
        self.base_url, self.task = base_url.rstrip("/"), task
        self.blocks: dict[Position, str] = {}
        data = self._call("POST", "/reset", {"task": asdict(task)})
        self.reset_message: str = data["message"]  # the commands that set up the start state
        self.server: str = server or data["server"]
        self._update(data)

    def observe(self) -> Observation:
        return self._update(self._call("GET", "/observe"))

    def step(self, action: Action) -> StepResult:
        data = self._call("POST", "/step", {"action": action.name, "target": action.target, "grid": action.grid})
        return StepResult(data["ok"], data["message"], data["output"], self._update(data["observation"]), data["events"])

    def _update(self, data: dict[str, Any]) -> Observation:
        obs = parse(data | {"server": self.server})
        self.position, self.actions, self.done, self.success = obs.position, obs.action_count, obs.done, obs.success
        x0, z0 = obs.position
        # Columns out of view stay as last seen; columns in view hold what is visible now.
        # ponytail: the view is the grid's diamond of RADIUS, so a block the adapter cannot see inside it (occluded, or
        # outside its 3D sphere) is forgotten until seen again; report the adapter's view if that costs real detours.
        self.blocks = {p: b for p, b in self.blocks.items() if abs(p[0] - x0) + abs(p[1] - z0) > RADIUS} | {
            (x, z): b for x, z, b in obs.visible
        }
        return obs

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        data = None if body is None else json.dumps(body).encode()
        request = Request(url, data, {"content-type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                return json.load(response)
        except HTTPError as err:
            with err:
                detail = err.read().decode(errors="replace")
            raise RuntimeError(f"{method} {url}: HTTP {err.code} {detail}") from err
        except OSError as err:  # refused, reset, or timed out
            raise RuntimeError(f"{method} {url}: {err}") from err
