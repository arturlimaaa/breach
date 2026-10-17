"""GridWorld's interface over the Node adapter's local HTTP contract (docs/design.md, "Adapter contract")."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .world import DIRECTIONS, HEADINGS, RADIUS, Action, Observation, Position, StepResult, Task

TIMEOUT = 90  # seconds; the adapter bounds a step at 60 s and serves one request at a time


def columns(data: dict[str, Any]) -> dict[Position, tuple[str, int]]:
    """Each visible column of an adapter observation as the visible block whose y is nearest the bot, with that y."""
    y = data["position"]["y"]
    # Farthest y first, so the nearest one is written last.
    return {(v["x"], v["z"]): (v["block"], v["y"]) for v in sorted(data["visible"], key=lambda v: -abs(v["y"] - y))}


def parse(data: dict[str, Any]) -> Observation:
    """An adapter observation on the core's (x, z) plane."""
    return Observation(
        data["server"], (data["position"]["x"], data["position"]["z"]), dict(data["inventory"]),
        [(*p, b) for p, (b, _) in columns(data).items()], data["action_count"], data["budget"], data["done"], data["success"],
    )


class HttpWorld:
    """The adapter behind the world interface the executor and B use. Every observation refreshes the attributes."""

    # The contract's move paths: {"toward": block} next to the nearest one in sight, {"heading", "blocks"} along a
    # heading, {"to": {x, y, z}} within reach of a position.
    paths = True

    def __init__(self, base_url: str, task: Task):
        """POST /reset with `task`. The rule scope `server` is the adapter's label, mc/<host>:<port>/<world> live."""
        self.base_url, self.task = base_url.rstrip("/"), task
        self.columns: dict[Position, tuple[str, int]] = {}
        data = self._call("POST", "/reset", {"task": asdict(task)})
        self.reset_message: str = data["message"]  # the commands that set up the start state
        self._update(data)

    @property
    def blocks(self) -> dict[Position, str]:
        return {p: b for p, (b, _) in self.columns.items()}

    def observe(self) -> Observation:
        return self._update(self._call("GET", "/observe"))

    def step(self, action: Action) -> StepResult:
        data = self._call("POST", "/step", {"action": action.name, "target": _target(action), "grid": action.grid})
        # An adapter from before `executed` evaluated every step it answered.
        return StepResult(
            data["ok"], data["message"], data["output"], self._update(data["observation"]), data["events"], data.get("executed", True),
        )

    def _update(self, data: dict[str, Any]) -> Observation:
        obs = parse(data)
        self.server, self.position, self.actions = obs.server, obs.position, obs.action_count
        self.done, self.success = obs.done, obs.success
        x0, z0 = obs.position
        # Columns out of view stay as last seen; columns in view hold what is visible now.
        # ponytail: the view is the grid's diamond of RADIUS, so a block the adapter cannot see inside it (occluded, or
        # outside its 3D sphere) is forgotten until seen again; report the adapter's view if that costs real detours.
        self.columns = {p: c for p, c in self.columns.items() if abs(p[0] - x0) + abs(p[1] - z0) > RADIUS} | columns(data)
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


def _target(action: Action) -> Any:
    """A move's target as the contract spells it. The core names a direction ("east"), a heading and block count ("E8",
    so the transition log keeps a string), a position ("to 48,72,-81"), or the block to path toward ("log")."""
    if action.name != "move" or action.target in DIRECTIONS:
        return action.target
    heading = re.fullmatch(r"([A-Z]{1,2})(\d+)", action.target or "")
    if heading and heading[1] in HEADINGS:
        return {"heading": heading[1], "blocks": int(heading[2])}
    position = re.fullmatch(r"to (-?\d+),(-?\d+),(-?\d+)", action.target or "")
    if position:
        return {"to": dict(zip("xyz", map(int, position.groups())))}
    return {"toward": action.target}
