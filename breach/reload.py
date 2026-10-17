"""HR: a vanilla world that loads one change just before the agent first uses the changed rule, as `/reload` does live."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .changes import Change, apply, goal_for
from .evaluate import Job, System
from .world import VANILLA, Action, GridWorld, StepResult, Task


class ReloadBeforeFirstUse:
    """`world`, except that `apply()` runs once, just before the first step that crafts the changed recipe or mines the changed block.

    `reload_step` is the log step of that first use, or None while no step has used the rule.
    """

    def __init__(self, world: GridWorld, change: Change, apply: Callable[[], None]):
        self._world, self._apply, self.change = world, apply, change
        self._key = ("mine", change.block) if change.kind == "drop" else ("craft", change.recipe)
        self.reload_step: int | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._world, name)

    def step(self, action: Action) -> StepResult:
        if self.reload_step is None and (action.name, action.target) == self._key:
            self._apply()
            self.reload_step = self._world.actions + 1
        return self._world.step(action)


def reloading(system: System, change: Change) -> System:
    """`system` on worlds that switch to `change`'s rules before its first use. A world that already has them stays as it is."""
    changed = apply(change, VANILLA)

    def run(world: GridWorld, *args: Any) -> Any:
        def load() -> None:
            world.ruleset = changed

        return system(ReloadBeforeFirstUse(world, change, load), *args)

    return run


def hr_task(change: Change) -> Task:
    """HC's goal for `change`, from an empty inventory."""
    return Task("hr", goal_for(change), budget=350)


def hr_jobs(change: Change, seed: int) -> list[Job]:
    """HR from a vanilla start, then HS on the server it left changed.

    run_jobs builds plain GridWorlds, so run these with a system from `reloading`, and with carry_memory for HS.
    """
    task, server = hr_task(change), f"grid/{change.id}"
    return [(task, seed, server, VANILLA, change.id), (replace(task, task_id="hs"), seed, server, apply(change, VANILLA), change.id)]
