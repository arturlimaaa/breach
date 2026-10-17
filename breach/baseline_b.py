from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import partial
from itertools import count, pairwise, repeat
from typing import Any, Callable, Iterator

from .log import Transition, TransitionLog, diff, obs_hash, verdict
from .rules import TOOL_TIERS, Rule
from .verify import classify
from .world import RADIUS, VANILLA, Action, GridWorld, Observation, Position, StepResult, held_tier, rules_from_ruleset

COOLDOWN = 5
State = dict[str, Any]
Option = tuple[str, Rule | None]


@dataclass(frozen=True)
class EpisodeResultB:
    success: bool
    actions: int
    planner_calls: int
    reason: str


def menu(bundled: list[Rule], obs: Observation, known: dict[Position, str]) -> dict[str, Option]:
    """Options from the observation, judged by the bundled table, never by the server's rules."""
    held, visible = Counter(obs.inventory), {b for *_, b in obs.visible}
    options: dict[str, Option] = {}
    for rule in bundled:
        if rule.action == "craft" and Counter(rule.inputs) <= held and (rule.near is None or held[rule.near]):
            options[f"craft {rule.target} x{rule.delta[rule.target]}"] = ("craft", rule)
        elif rule.action == "mine" and TOOL_TIERS[rule.tool] <= held_tier(held):
            if rule.target in visible:
                options[f"mine {rule.target}"] = ("mine", rule)
            elif rule.target in known.values():
                options[f"move toward {rule.target}"] = ("move", rule)
    return options | {"explore": ("explore", None), "wait": ("wait", None)}


def default_choose(state: State, options: dict[str, Option]) -> str:
    """Craft the objective, else craft, mine, or move toward a missing target, else explore, else wait."""
    missing = {item for item, n in state["targets"].items() if state["inventory"].get(item, 0) < n}

    def rank(key: str) -> int:
        kind, rule = options[key]
        if kind == "craft" and rule.target == state["objective"]:
            return 0
        if rule is not None and missing & rule.outputs.keys():
            return ("craft", "mine", "move").index(kind) + 1
        return {"explore": 4, "wait": 5}.get(kind, 6)

    return min(options, key=rank)


def step_and_log(world: GridWorld, log: TransitionLog, episode: str, action: Action, rule: Rule | None = None) -> StepResult:
    """Take one action and log it the executor's way, predicting the bundled `rule`'s delta."""
    before = world.observe()
    result = world.step(action)
    predicted = dict(rule.delta) if rule else {}
    observed = diff(before.inventory, result.observation.inventory)
    target = rule.target if rule else action.target
    cls = classify(action.name, target)
    log.append(Transition(
        episode, world.actions, world.server, obs_hash(before), action.name, target,
        f"bundled:{rule.rule_id}" if rule else None, predicted, observed, cls,
        verdict(cls, predicted, observed, result.ok, result.events), ok=result.ok, events=list(result.events),
    ))
    return result


def run_episode_b(
    world: GridWorld,
    log: TransitionLog,
    episode: str,
    plan_fn: Callable[[State], State],
    choose_fn: Callable[[State, dict[str, Option]], str] = default_choose,
) -> EpisodeResultB:
    """rmalde/minecraft-agent's loop on the grid. Mismatches are logged and never acted on."""
    bundled = rules_from_ruleset(VANILLA)
    known: dict[Position, str] = {}
    cooldown: dict[str, int] = {}
    failures: list[str] = []
    plan: State = {}
    calls = 0
    spiral = _spiral()
    act = partial(step_and_log, world, log, episode)

    # ponytail: a wait is a decision without a world action, so decisions are capped at the action budget.
    for step in range(1, world.task.budget + 1):
        if world.done:
            break
        obs = world.observe()
        known = {p: b for p, b in known.items() if _distance(p, obs.position) > RADIUS} | {(x, z): b for x, z, b in obs.visible}
        options = {k: v for k, v in menu(bundled, obs, known).items() if cooldown.get(k, 0) < step}
        state = {"goal": world.task.goal, "count": world.task.count, "inventory": obs.inventory, "failures": failures}
        if step == 1 or len(failures) >= 3 or options.keys() == {"wait"}:
            # ponytail: synchronous, so a plan costs no actions; rmalde's planner is async and B acts while it thinks.
            plan, failures, calls = plan_fn(state), [], calls + 1
        key = choose_fn(state | plan, options)
        kind, rule = options[key]
        if kind == "wait":
            continue
        if kind == "mine":
            target = _nearest(known, rule.target, world.position)
            while world.position != target and not world.done:
                act(Action("move", _heading(world.position, target)))
            if world.done:
                break
        if kind == "explore":
            result = act(Action("move", next(spiral)))
        elif kind == "move":
            result = act(Action("move", _heading(world.position, _nearest(known, rule.target, world.position))))
        else:
            result = act(Action(kind, rule.target if kind == "craft" else None), rule)
        if result.ok:
            failures = []
        else:
            cooldown[key] = step + COOLDOWN
            failures = [*failures, f"{key}: {result.message}"]
    return EpisodeResultB(world.success, world.actions, calls, "goal" if world.success else "budget")


def immediate_repeat_rate(log: TransitionLog) -> float:
    """Share of exact mismatches whose next transition, in the same episode, has the same action and target."""
    repeats = [
        nxt is not None and (nxt.episode, nxt.action, nxt.target) == (t.episode, t.action, t.target)
        for t, nxt in pairwise([*log, None])
        if t.cls == "exact" and t.verdict == "mismatch" and not t.test
    ]
    return sum(repeats) / len(repeats) if repeats else 0.0


def _distance(a: Position, b: Position) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _nearest(known: dict[Position, str], block: str, position: Position) -> Position:
    return min((p for p, b in known.items() if b == block), key=lambda p: _distance(p, position))


def _heading(src: Position, dst: Position) -> str:
    dx, dz = dst[0] - src[0], dst[1] - src[1]
    return ("east" if dx > 0 else "west") if dx else ("south" if dz > 0 else "north")


def _spiral() -> Iterator[str]:
    """Square spiral: 1 east, 1 south, 2 west, 2 north, 3 east, ..."""
    for leg in count(1):
        for direction in ("east", "south") if leg % 2 else ("west", "north"):
            yield from repeat(direction, leg)
