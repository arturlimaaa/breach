from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import count, cycle, islice, repeat

from .certify import certify, demote
from .log import Transition, TransitionLog, diff, obs_hash, verdict
from .planner import Step, plan
from .recover import Induce, recover
from .store import RuleStore
from .verify import classify
from .world import DIRECTIONS, HEADINGS, Action, GridWorld, Position, StepResult


@dataclass(frozen=True)
class EpisodeResult:
    success: bool
    actions: int
    reason: str


class Executor:
    """Runs plans from the store one step at a time, verifying each step against the next observation.

    With `check` off (system C) every verdict is logged and none is acted on.
    """

    def __init__(
        self, world: GridWorld, store: RuleStore, log: TransitionLog, episode: str, induce: Induce | None = None, check: bool = True
    ):
        self.world, self.store, self.log, self.episode = world, store, log, episode
        self.induce, self.check = induce, check
        self.known: dict[Position, str] = {}
        self.steps = 0
        self.rounds: Counter[tuple[str, str]] = Counter()
        self.unknown: list[str] = []

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
        predicted = dict(step.delta) if step else {}
        # A mine action names no block; the step does, and both the exact whitelist and the metrics need it.
        target = step.target if step else action.target
        if action.name == "probe":
            # A probe consumes nothing; a test probe is checked exactly on what the output slot shows.
            observed, cls = result.output or {}, "exact"
        else:
            observed, cls = diff(before.inventory, result.observation.inventory), classify(action.name, target)
        self.steps += 1
        transition = Transition(
            self.episode, self.steps, self.world.server, obs_hash(before), action.name, target,
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
        target = self.nearest(block)
        while self.world.position != target and not self.world.done:
            dx, dz = target[0] - self.world.position[0], target[1] - self.world.position[1]
            direction = ("east" if dx > 0 else "west") if dx else ("south" if dz > 0 else "north")
            self.act(Action("move", direction))
        return self.world.position == target

    def explore_until(self, block: str) -> bool:
        """Look; walk up to 8 moves along the nearest heading that shows the block, else one spiral leg; repeat until it is in sight."""
        legs = _spiral_legs()
        while not self.world.done:
            _, glance = self.act(Action("look"))
            sightings = {h: s["distance"] for h, s in (glance.output or {}).items() if s["block"] == block}
            if sightings:
                dx, dz = HEADINGS[min(sightings, key=sightings.get)]
                # A diagonal heading alternates its two cardinal moves.
                path = islice(cycle([d for d, offset in DIRECTIONS.items() if offset in ((dx, 0), (0, dz))]), 8)
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
        return False

    def run(self) -> EpisodeResult:
        task = self.world.task
        while not self.world.done:
            inventory, server = dict(self.observe().inventory), self.world.server
            steps = plan(task.goal, task.count, inventory, self.store.usable(server), self.distance)
            if steps is None:
                steps = plan(task.goal, task.count, inventory, self.store.usable(server, hypotheses=True), self.distance)
            if steps is None:
                return EpisodeResult(False, self.world.actions, f"unrecoverable {self.unknown[-1]}" if self.unknown else "no certified plan")
            hit = self.execute(steps)
            reason = self.refuted(hit) if isinstance(hit, Transition) else hit
            if reason is not None:
                return EpisodeResult(False, self.world.actions, reason)
        return EpisodeResult(self.world.success, self.world.actions, "goal" if self.world.success else "budget")

    def execute(self, steps: list[Step]) -> Transition | str | None:
        """Act out `steps`. Returns the step that refuted its rule, a reason the episode cannot go on, or None to replan."""
        for step in steps:
            if self.world.done:
                return None
            if step.action == "mine" and not self.travel_to(step.target):
                return None if self.world.done else f"no reachable {step.target}"
            if self.world.done:
                return None
            transition, _ = self.act(Action(step.action, step.target if step.action == "craft" else None), step)
            if not self.check:
                continue
            if transition.cls == "exact" and transition.verdict == "mismatch":
                return transition
            # The event may have moved the inventory off the plan; finishing it would blame the next rule.
            if transition.verdict == "quarantined":
                return None
            # A certified rule plans as an ordinary step, so the rest of this plan is stale.
            if step.test and transition.verdict == "match" and certify(self.store, self.log, step.rule_id).reason == "certified":
                return None
        return None

    def refuted(self, transition: Transition) -> str | None:
        """Demote the refuted rule on this server, then recover it. Without an inducer a refuted certified rule ends the episode."""
        rule = demote(self.store, transition.rule_id, self.world.server)
        if self.induce is None:
            return None if transition.test else f"contradiction at {transition.rule_id}"
        # Candidates a round left untested when the budget ran out get tested by planning before the model is asked again.
        if any(r.key == rule.key and r.status == "hypothesis" for r in self.store.usable(self.world.server, hypotheses=True)):
            return None
        return recover(self, rule, transition)


def _spiral_legs():
    """Square spiral as (direction, length) legs: 1 east, 1 south, 2 west, 2 north, 3 east, ..."""
    for n in count(1):
        for direction in ("east", "south") if n % 2 else ("west", "north"):
            yield direction, n


def run_episode(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str, induce: Induce | None = None) -> EpisodeResult:
    return Executor(world, store, log, episode, induce).run()


def run_episode_c(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResult:
    """System C: rules without the step check. It follows each plan to its end and replans only then."""
    return Executor(world, store, log, episode, check=False).run()
