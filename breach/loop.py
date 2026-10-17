from __future__ import annotations

from dataclasses import dataclass

from .certify import demote
from .log import Transition, TransitionLog, diff, obs_hash, verdict
from .planner import Step, plan
from .store import RuleStore
from .verify import classify
from .world import DIRECTIONS, Action, GridWorld, Position


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

    def act(self, action: Action, step: Step | None = None) -> Transition:
        before = self.observe()
        result = self.world.step(action)
        observed = diff(before.inventory, result.observation.inventory)
        predicted = dict(step.delta) if step else {}
        # A mine action names no block; the step does, and both the exact whitelist and the metrics need it.
        target = step.target if step else action.target
        cls = classify(action.name, target)
        self.steps += 1
        transition = Transition(
            self.episode, self.steps, self.world.server, obs_hash(before), action.name, target,
            step.rule_id if step else None, predicted, observed, cls,
            verdict(cls, predicted, observed, result.ok, result.events), step.test if step else False,
            result.ok, result.events,
        )
        self.log.append(transition)
        return transition

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
        """Square spiral outward until a block of the wanted type is seen."""
        leg = 1
        for direction in _cycle(("east", "south", "west", "north")):
            for _ in range(leg):
                if self.world.done:
                    return False
                self.act(Action("move", direction))
                self.observe()
                if self.nearest(block) is not None:
                    return True
            if direction in ("south", "north"):
                leg += 1
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
                    return EpisodeResult(False, self.world.actions, f"no reachable {step.target}")
                if self.world.done:
                    break
                action = Action(step.action, step.target if step.action == "craft" else None)
                transition = self.act(action, step)
                if transition.cls == "exact" and transition.verdict == "mismatch":
                    demote(self.store, step.rule_id, self.world.server)
                    # ponytail: M2 replaces this return with induction and re-certification.
                    return EpisodeResult(False, self.world.actions, f"contradiction at {step.rule_id}")
                # The event may have moved the inventory off the plan; finishing it would blame the next rule.
                if transition.verdict == "quarantined":
                    break
        return EpisodeResult(self.world.success, self.world.actions, "goal" if self.world.success else "budget")


def _cycle(items):
    while True:
        yield from items


def run_episode(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResult:
    return Executor(world, store, log, episode).run()
