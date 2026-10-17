from __future__ import annotations

from dataclasses import dataclass
from itertools import chain, count, cycle, islice, repeat

from .certify import demote
from .log import Transition, TransitionLog, diff, obs_hash, verdict
from .planner import Step, plan
from .store import RuleStore
from .verify import classify
from .world import DIRECTIONS, HEADINGS, Action, GridWorld, Position, StepResult

# ponytail: 8 legs walk 4 blocks out, 12 with the view; a block farther from the start needs an adapter look that reports headings.
SPIRAL_LEGS = 8


@dataclass(frozen=True)
class EpisodeResult:
    success: bool
    actions: int
    reason: str


class Executor:
    """Runs plans from the store one step at a time, verifying each step against the next observation."""

    def __init__(self, world: GridWorld, store: RuleStore, log: TransitionLog, episode: str):
        self.world, self.store, self.log, self.episode = world, store, log, episode
        self.known: dict[Position, str] = {}
        self.steps = 0

    def observe(self):
        obs = self.world.observe()
        for x, z, block in obs.visible:
            self.known[(x, z)] = block
        for pos in [p for p, _ in self.known.items() if p not in self.world.blocks]:
            del self.known[pos]
        return obs

    def act(self, action: Action, step: Step | None = None) -> tuple[Transition, StepResult]:
        before = self.observe()
        result = self.world.step(action)
        observed = diff(before.inventory, result.observation.inventory)
        predicted = dict(step.delta) if step else {}
        cls = classify(action.name, action.target)
        self.steps += 1
        transition = Transition(
            self.episode, self.steps, self.world.server, obs_hash(before), action.name, action.target,
            step.rule_id if step else None, predicted, observed, cls,
            verdict(cls, predicted, observed, result.ok, result.events), step.test if step else False,
            result.ok, result.events,
        )
        self.log.append(transition)
        return transition, result

    def nearest(self, block: str) -> Position | None:
        x0, z0 = self.world.position
        candidates = [p for p, b in self.known.items() if b == block]
        return min(candidates, key=lambda p: abs(p[0] - x0) + abs(p[1] - z0), default=None)

    def distance(self, block: str) -> int | None:
        target = self.nearest(block)
        if target is None:
            return None
        return abs(target[0] - self.world.position[0]) + abs(target[1] - self.world.position[1])

    def travel_to(self, block: str) -> bool:
        self.observe()
        if self.nearest(block) is None and not self.explore_until(block):
            return False
        if self.world.paths:
            # One move paths next to the block and the mine walks the last metre. A failed path is not retried.
            return not self.world.done and self.act(Action("move", block))[1].ok
        target = self.nearest(block)
        while self.world.position != target and not self.world.done:
            dx, dz = target[0] - self.world.position[0], target[1] - self.world.position[1]
            direction = ("east" if dx > 0 else "west") if dx else ("south" if dz > 0 else "north")
            self.act(Action("move", direction))
        return self.world.position == target

    def explore_until(self, block: str) -> bool:
        """Look; walk up to 8 moves along the nearest heading that shows the block, else one spiral leg; repeat until it is in sight.

        The adapter's look reports no headings, so on a pathing world a look that does not show the block is followed by the
        first SPIRAL_LEGS legs of the spiral, and then exploring stops.
        """
        legs = _spiral_legs()
        while not self.world.done:
            _, glance = self.act(Action("look"))
            sightings = {h: s["distance"] for h, s in (glance.output or {}).items() if s["block"] == block}
            if sightings:
                dx, dz = HEADINGS[min(sightings, key=sightings.get)]
                # A diagonal heading alternates its two cardinal moves.
                path = islice(cycle([d for d, offset in DIRECTIONS.items() if offset in ((dx, 0), (0, dz))]), 8)
            elif self.world.paths:
                path = chain.from_iterable(repeat(*leg) for leg in islice(legs, SPIRAL_LEGS))
            else:
                # ponytail: when nearer blocks mask every heading this is the O(r²) spiral again; head for the emptiest heading if that stalls.
                path = repeat(*next(legs))
            for direction in path:
                if self.world.done:
                    return False
                self.act(Action("move", direction))
                self.observe()
                if self.nearest(block) is not None:
                    return True
            if self.world.paths and not sightings:
                return False
        return False

    def run(self) -> EpisodeResult:
        task = self.world.task
        while not self.world.done:
            obs = self.observe()
            steps = plan(task.goal, task.count, dict(obs.inventory), self.store.usable(self.world.server), self.distance)
            if steps is None:
                return EpisodeResult(False, self.world.actions, "no certified plan")
            for step in steps:
                if self.world.done:
                    break
                if step.action == "mine" and not self.travel_to(step.target):
                    if self.world.done:
                        break
                    return EpisodeResult(False, self.world.actions, f"no reachable {step.target}")
                if self.world.done:
                    break
                grid = {item: -n for item, n in step.delta.items() if n < 0} if step.action == "craft" else None
                transition, _ = self.act(Action(step.action, step.target, grid), step)
                if transition.cls == "exact" and transition.verdict == "mismatch":
                    demote(self.store, step.rule_id, self.world.server)
                    # ponytail: M2 replaces this return with induction and re-certification.
                    return EpisodeResult(False, self.world.actions, f"contradiction at {step.rule_id}")
                # The event may have moved the inventory off the plan; finishing it would blame the next rule.
                if transition.verdict == "quarantined":
                    break
        return EpisodeResult(self.world.success, self.world.actions, "goal" if self.world.success else "budget")


def _spiral_legs():
    """Square spiral as (direction, length) legs: 1 east, 1 south, 2 west, 2 north, 3 east, ..."""
    for n in count(1):
        for direction in ("east", "south") if n % 2 else ("west", "north"):
            yield direction, n


def run_episode(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResult:
    return Executor(world, store, log, episode).run()
