"""runs/<run>/status.json for the dashboard and the OBS banner (site/README.md): the plan diff, the last step,
the rule in focus and the text-model cost of the episode in progress."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .planner import Step
from .rules import Rule

if TYPE_CHECKING:
    from .loop import Executor

Writer = Callable[[dict[str, Any]], None]


def status_file(path: Path) -> Writer:
    """Replace `path` whole on every write, so a poll never reads half a file.

    `started` is the run start: an episode writing to a run's status file keeps the start an earlier episode wrote.
    """
    try:
        started = json.loads(path.read_text(encoding="utf-8"))["started"]
    except (OSError, ValueError, KeyError, TypeError):
        started = _now()

    def write(status: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**status, "started": started, "updated": _now()}) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    return write


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def shown(rule: Rule, note: str = "", status: str | None = None) -> dict[str, Any]:
    """A rule as the banner shows it. A certified revision of another rule is "recertified"."""
    status = status or ("recertified" if rule.status == "certified" and rule.revision_of else rule.status)
    return {"rule_id": rule.rule_id, "status": status, "evidence": len(rule.evidence), "note": note}


def change(rule: Rule) -> str:
    return ", ".join(f"{item} {n:+d}" for item, n in sorted(rule.delta.items()))


class Status:
    """What one episode shows. The plan keeps every plan of the episode; only steps of the latest can be current or pending."""

    def __init__(self, write: Writer | None):
        self.write = write
        self.plan: list[dict[str, str]] = []
        self.left: list[tuple[Step, dict[str, str]]] = []  # the latest plan's steps that have not acted, current first
        self.rule: dict[str, Any] | None = None
        self.calls, self.latency_ms = 0, None

    def planned(self, steps: list[Step]) -> None:
        """Abort what is left of the last plan, then append this one with its first step current."""
        self.abort()
        self.left = [(s, {"rule_id": s.rule_id, "action": s.action, "target": s.target, "status": "pending"}) for s in steps]
        self.plan += [entry for _, entry in self.left]
        if self.left:
            self.left[0][1]["status"] = "current"

    def acted(self, step: Step | None) -> bool:
        """Mark the current plan step done when `step` is it, and the next one current. Acquisition and test steps are not plan steps."""
        if not self.left or step is not self.left[0][0]:
            return False
        self.left.pop(0)[1]["status"] = "done"
        if self.left:
            self.left[0][1]["status"] = "current"
        return True

    def abort(self) -> None:
        for _, entry in self.left:
            entry["status"] = "aborted"
        self.left = []

    def emit(self, ex: Executor) -> None:
        if self.write is None:
            return
        last = ex.last
        self.write({
            "episode": ex.episode, "server": ex.world.server, "goal": ex.world.task.goal, "step": ex.steps,
            "budget": ex.world.task.budget, "plan": [dict(entry) for entry in self.plan],
            "last": None if last is None else {
                "action": last.action, "target": last.target, "rule_id": last.rule_id,
                "predicted": last.predicted, "observed": last.observed, "verdict": last.verdict,
            },
            "rule": self.rule, "model": {"calls": self.calls, "last_latency_ms": self.latency_ms},
        })
