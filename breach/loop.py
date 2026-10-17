from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import count, cycle, islice, repeat
from pathlib import Path

from .certify import certify, demote
from .log import Transition, TransitionLog, diff, obs_hash, verdict
from .planner import Step, plan
from .recover import Induce, adopt, recover
from .rules import Rule
from .status import Status, shown, status_file
from .store import RuleStore
from .verify import classify
from .world import DIRECTIONS, HEADINGS, Action, GridWorld, Position, StepResult, within

# ponytail: after a look with no output, 8 legs walk 4 blocks out, 12 with the view; look again if failed looks strand live runs.
SPIRAL_LEGS = 8
COMPASS = {"east": "E", "south": "S", "west": "W", "north": "N"}


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
        self, world: GridWorld, store: RuleStore, log: TransitionLog, episode: str,
        induce: Induce | None = None, check: bool = True, status_path: Path | None = None,
    ):
        self.world, self.store, self.log, self.episode = world, store, log, episode
        self.induce, self.check = induce, check
        self.known: dict[Position, str] = {}
        self.steps = 0
        self.last: Transition | None = None
        self.rounds: Counter[tuple[str, str]] = Counter()
        self.unrecovered: list[str] = []
        self.status = Status(status_file(status_path) if status_path else None)

    def record(self, rule: Rule) -> Rule:
        """This server's record for the rule's key: a candidate revises its record, and the record revises the global rule."""
        parent = self.store.rules.get(rule.revision_of or "")
        return parent if parent is not None and parent.scope == rule.scope else rule

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
        if action.name == "probe":
            # A probe consumes nothing; a test probe the world ran is checked exactly on what the output slot shows.
            observed, cls = result.output or {}, "exact" if result.executed else "tolerant"
        else:
            observed, cls = diff(before.inventory, result.observation.inventory), classify(action.name, action.target, result.executed, result.output)
        self.steps += 1
        transition = Transition(
            self.episode, self.steps, self.world.server, obs_hash(before), action.name, action.target,
            step.rule_id if step else None, predicted, observed, cls,
            verdict(cls, predicted, observed, result.ok, result.events), step.test if step else False,
            result.ok, result.events,
        )
        self.log.append(transition)
        self.last = transition
        if self.status.acted(step):
            self.status.rule = shown(self.store.rules[step.rule_id])
        self.status.emit(self)
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
        if self.world.paths:
            # One move paths next to the block and the mine walks the last metre: toward a block in view, else to the
            # column a remembered one was seen in, at its y. A failed path is not retried.
            x, z = target
            in_view = any(b == block for *_, b in self.observe().visible)
            move = block if in_view else f"to {x},{self.world.columns[target][1]},{z}"
            return not self.world.done and self.act(Action("move", move))[1].ok
        while self.world.position != target and not self.world.done:
            self.act(Action("move", _heading(self.world.position, target)))
        return self.world.position == target

    def station(self, block: str) -> bool:
        """Bring a `block` within reach for a craft or probe: walk to the nearest one on the map, else place the one held."""
        self.observe()
        if any(b == block and within(p, self.world.position) for p, b in self.known.items()):
            return True
        if self.nearest(block) is not None:
            return self.travel_to(block)
        return not self.world.done and self.act(Action("place", block))[1].ok

    def explore_until(self, block: str) -> bool:
        """Look for the block; walk up to 8 moves along the nearest heading that shows one, else one spiral leg; repeat until it is in sight."""
        if self.world.paths:
            return self.explore_by_heading(block)
        legs = _spiral_legs()
        while not self.world.done:
            _, glance = self.act(Action("look", block))
            sightings = {h: s["distance"] for h, s in (glance.output or {}).items() if s["block"] == block}
            if sightings:
                dx, dz = HEADINGS[min(sightings, key=sightings.get)]
                # A diagonal heading alternates its two cardinal moves.
                path = islice(cycle([d for d, offset in DIRECTIONS.items() if offset in ((dx, 0), (0, dz))]), 8)
            else:
                # ponytail: with no block of the type in any corridor this is the O(r²) spiral; widen the corridors if that stalls.
                path = repeat(*next(legs))
            for direction in path:
                if self.world.done:
                    return False
                self.act(Action("move", direction))
                self.observe()
                if self.nearest(block) is not None:
                    return True
        return False

    def explore_by_heading(self, block: str) -> bool:
        """Exploring a pathing world, where a step can be a path: look, then one heading move toward the nearest heading that
        shows the block, at most 8 blocks, else one along the next spiral leg; repeat until the block is in view.

        A heading move's target is the heading and its block count, such as "E8". After a failed move the next leg turns
        instead of retrying that heading. A look with no output, which is what a failed adapter look returns, allows the
        first SPIRAL_LEGS legs without looking again, then exploring stops.
        """
        legs, failed = _spiral_legs(), None
        while not self.world.done:
            _, glance = self.act(Action("look", block))
            sightings = {h: s["distance"] for h, s in (glance.output or {}).items() if s["block"] == block}
            best = min(sightings, key=sightings.get, default=None)
            if glance.output is None:
                moves = [(COMPASS[direction], n) for direction, n in islice(legs, SPIRAL_LEGS)]
            elif best is not None and best != failed:
                moves = [(best, min(sightings[best], 8))]
            else:
                direction, n = next(legs)
                if COMPASS[direction] == failed:
                    direction, n = next(legs)
                moves = [(COMPASS[direction], n)]
            for heading, n in moves:
                if self.world.done:
                    return False
                failed = None if self.act(Action("move", f"{heading}{n}"))[1].ok else heading
                self.observe()
                if self.nearest(block) is not None:
                    return True
            if glance.output is None:
                return False
        return False

    def run(self) -> EpisodeResult:
        reason = self.pursue()
        self.status.abort()
        self.status.emit(self)
        # The world decides the outcome: a refuting step can also meet the goal.
        return EpisodeResult(self.world.success, self.world.actions, reason)

    def pursue(self) -> str:
        """Plan and act until the goal or the budget; the reason the episode ends."""
        task = self.world.task
        while not self.world.done:
            inventory, server = dict(self.observe().inventory), self.world.server
            on_map = set(self.known.values())
            steps = plan(task.goal, task.count, inventory, self.store.usable(server), self.distance, on_map)
            if steps is None:
                steps = plan(task.goal, task.count, inventory, self.store.usable(server, hypotheses=True), self.distance, on_map)
            if steps is None:
                return self.unrecovered[-1] if self.unrecovered else "no certified plan"
            self.status.planned(steps)
            self.status.emit(self)
            hit = self.execute(steps)
            reason = self.refuted(hit) if isinstance(hit, Transition) else hit
            if reason is not None:
                return reason
        return "goal" if self.world.success else "budget"

    def execute(self, steps: list[Step]) -> Transition | str | None:
        """Act out `steps`. Returns the step that refuted its rule, a reason the episode cannot go on, or None to replan."""
        for step in steps:
            if self.world.done:
                return None
            # The block a mine walks to, or the station a craft needs within reach.
            needed = step.target if step.action == "mine" else step.near if step.action == "craft" else None
            reached = needed is None or (self.travel_to(needed) if step.action == "mine" else self.station(needed))
            if self.world.done:
                return None
            # A pathing world's mine or craft walks the last stretch itself, so there only its refusal proves the block out of reach.
            if not reached and not (self.world.paths and self.nearest(needed) is not None):
                return f"no reachable {needed}"
            grid = {item: -n for item, n in step.delta.items() if n < 0} if step.action == "craft" else None
            transition, result = self.act(Action(step.action, step.target, grid), step)
            if not reached and not result.executed:
                return f"no reachable {needed}"
            if not self.check:
                continue
            if transition.cls == "exact" and transition.verdict == "mismatch":
                return transition
            # An event or a mine that left its block put the inventory off the plan; finishing it would blame the next rule.
            if transition.verdict in ("quarantined", "mismatch"):
                return None
            if step.test and transition.verdict == "match" and self.confirmed(step.rule_id):
                return None
        return None

    def confirmed(self, rule_id: str) -> bool:
        """A test step matched: a candidate becomes its record, then the record certifies if the log allows. True when the plan is stale."""
        rule = self.store.rules[rule_id]
        record = self.record(rule)
        if record is not rule:
            adopt(self.store, rule)
        certification = certify(self.store, self.log, record.rule_id)
        self.status.rule = shown(certification.rule, certification.reason)
        self.status.emit(self)
        # An adopted candidate plans under its record from now on, and a certified rule as an ordinary step.
        return record is not rule or certification.reason == "certified"

    def refuted(self, transition: Transition) -> str | None:
        """Demote the refuted rule on this server, then recover its record. Without an inducer a refuted certified rule ends the episode."""
        demoted = demote(self.store, transition.rule_id, self.world.server)
        record = self.record(demoted)
        self.status.abort()
        self.status.rule = shown(record, f"contradicted at {transition.episode}/{transition.step}")
        self.status.emit(self)
        if self.induce is None:
            return None if transition.test else f"contradiction at {transition.rule_id}"
        # Candidates a round left untested when the budget ran out get tested by planning before the model is asked again.
        if any(r.key == record.key and r.status == "hypothesis" for r in self.store.usable(self.world.server, hypotheses=True)):
            return None
        # Recovery runs even when the refuting step met the goal, so the next task on this server finds a tested revision.
        return recover(self, record, transition)


def _spiral_legs():
    """Square spiral as (direction, length) legs: 1 east, 1 south, 2 west, 2 north, 3 east, ..."""
    for n in count(1):
        for direction in ("east", "south") if n % 2 else ("west", "north"):
            yield direction, n


def _heading(src: Position, dst: Position) -> str:
    dx, dz = dst[0] - src[0], dst[1] - src[1]
    return ("east" if dx > 0 else "west") if dx else ("south" if dz > 0 else "north")


def run_episode(
    world: GridWorld, store: RuleStore, log: TransitionLog, episode: str, induce: Induce | None = None, status_path: Path | None = None,
) -> EpisodeResult:
    return Executor(world, store, log, episode, induce, status_path=status_path).run()


def run_episode_c(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str, status_path: Path | None = None) -> EpisodeResult:
    """System C: rules without the step check. It follows each plan to its end and replans only then."""
    return Executor(world, store, log, episode, check=False, status_path=status_path).run()
