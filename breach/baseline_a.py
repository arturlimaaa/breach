"""System A: the text model plans each task as B's menu keys, from scratch. No memory, no step check."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from .baseline_b import Option, _distance, _heading, _nearest, _spiral, menu, step_and_log
from .induce import _FENCE
from .llm import complete
from .log import TransitionLog
from .planner import plan
from .rules import Rule
from .world import RADIUS, VANILLA, Action, GridWorld, Observation, Position, Task, rules_from_ruleset

MAX_CALLS = 8


@dataclass(frozen=True)
class EpisodeResultA:
    success: bool
    actions: int
    model_calls: int
    reason: str


def run_episode_a(world: GridWorld, log: TransitionLog, episode: str, complete: Callable[..., str] = complete) -> EpisodeResultA:
    """Run the model's plan key by key. A missing key, a failed action, or a short plan goes back to the model."""
    bundled = rules_from_ruleset(VANILLA)
    act = partial(step_and_log, world, log, episode)
    known: dict[Position, str] = {}
    spiral = _spiral()
    messages: list[dict[str, str]] = []
    head = _prompt(world.task, bundled)
    calls = 0
    while not world.done:
        if calls == MAX_CALLS:
            return EpisodeResultA(False, world.actions, calls, "calls exhausted")
        obs = world.observe()
        known, options = _look(bundled, obs, known)
        messages = [*messages, {"role": "user", "content": f"{head}\n\n{_state(obs, options)}"}]
        reply = complete(messages, episode=episode, step=world.actions, purpose="plan", thinking=False)
        calls += 1
        messages = [*messages, {"role": "assistant", "content": reply}]
        try:
            keys = _keys(reply)
        except ValueError as exc:
            head = f"No plan in that reply: {exc}."
            continue
        head = "The plan ran out before the goal."
        for key in keys:
            if world.done:
                break
            known, options = _look(bundled, world.observe(), known)
            if key not in options:
                head = f'"{key}" is not available now.'
                break
            kind, rule = options[key]
            if kind == "wait":
                continue
            # ponytail: a copy of run_episode_b's option execution; lift one shared helper when either copy must change.
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
            if not result.ok:
                head = f'"{key}" failed: {result.message}.'
                break
    return EpisodeResultA(world.success, world.actions, calls, "goal" if world.success else "budget")


def vanilla_replanner(world: GridWorld, env: Mapping[str, str] | None = None) -> tuple[Callable[..., str], list]:
    """Fake Nemotron that knows only vanilla: every call answers the vanilla plan from the world's inventory.

    The answer comes from a fake endpoint behind `llm.complete`, so a BREACH_RUN_DIR in `env` logs each call as a real one.
    """
    calls = []
    rules = rules_from_ruleset(VANILLA, status="certified")
    # The dummy key passes llm.complete's check; the model name marks the logged calls as this fake.
    offline = {"BREACH_LLM_API_KEY": "offline", "BREACH_LLM_MODEL": "vanilla-replanner", **(env or {})}

    def endpoint(url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        steps = plan(world.task.goal, world.task.count, world.observe().inventory, rules, lambda block: 1)
        keys = [f"craft {s.target} x{s.delta[s.target]}" if s.action == "craft" else f"mine {s.target}" for s in steps]
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(keys)}}]}).encode()

    def replan(messages, **kwargs):
        calls.append((messages, kwargs))
        return complete(messages, **kwargs, transport=endpoint, env=offline)

    return replan, calls


def _look(bundled: list[Rule], obs: Observation, known: dict[Position, str]) -> tuple[dict[Position, str], dict[str, Option]]:
    """B's block memory and menu for this observation."""
    known = {p: b for p, b in known.items() if _distance(p, obs.position) > RADIUS} | {(x, z): b for x, z, b in obs.visible}
    return known, menu(bundled, obs, known)


def _keys(reply: str) -> list[str]:
    fenced = _FENCE.search(reply)
    keys = json.loads(fenced.group(1) if fenced else reply)
    if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
        raise ValueError("a plan is a JSON array of option strings")
    return keys


def _prompt(task: Task, bundled: list[Rule]) -> str:
    """The task and the bundled table, one line per menu key spelled as `menu` spells it."""
    lines = []
    for rule in bundled:
        if rule.action == "craft":
            key, needs = f"craft {rule.target} x{rule.delta[rule.target]}", rule.near
        else:
            key, needs = f"mine {rule.target}", rule.tool
        lines.append(f'- "{key}": {json.dumps(rule.delta)}' + (f", needs a {needs} held" if needs else ""))
    return "\n".join([
        f"Plan a task in a 2D grid version of Minecraft: hold {task.count} {task.goal} within {task.budget} actions.",
        "",
        "Options and the inventory change each one causes, negative consumed and positive produced:",
        *lines,
        '- "move toward <block>": one step toward the nearest <block> seen before and now out of view',
        '- "explore": one step along an outward square spiral',
        '- "wait": no action',
        "A craft needs its inputs held. A mine needs the block in view and first walks to the nearest one. "
        "Every craft, mine, and step costs one action.",
    ])


def _state(obs: Observation, options: dict[str, Option]) -> str:
    view = ", ".join(f"{block} at ({x}, {z})" for x, z, block in obs.visible) or "nothing"
    return "\n".join([
        f"Actions used: {obs.action_count} of {obs.budget}. Position: {obs.position}.",
        f"Inventory: {json.dumps(obs.inventory, sort_keys=True)}",
        f"In view: {view}",
        f"Available now: {json.dumps(list(options))}",
        "Reply with only a JSON array of options to run in order.",
    ])
