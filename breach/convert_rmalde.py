"""System B's run directory from rmalde/minecraft-agent's runs/<run>/events.jsonl, for `python3 -m breach.proof`.

agent.mjs logs a `decision` (the menu key Jev chose) before each action and a `result` (its description, outcome and
the inventory after it) once the action ends. Each result becomes one transition, predicted by our bundled table
rules_from_ruleset(VANILLA) as B on the grid is. The episode ends like a grid episode, at the first result that holds
the goal or at the budget; whatever his agent does after that is not part of it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

from .live import TASKS
from .log import Transition, TransitionLog, diff, verdict
from .verify import classify
from .world import VANILLA, Task, rules_from_ruleset

SERVER = "mc/127.0.0.1:25565/world"  # the adapter's label for our server's world
BUNDLED = {(rule.action, rule.target): rule for rule in rules_from_ruleset(VANILLA)}
# Menu key prefixes in agent.mjs's candidates(): resources to mine, then ways to walk.
MINES = ("logs(", "beds(", "food(", "stone(", "iron(", "fuel(", "blocks(")
MOVES = ("waypoint", "detour_", "approach_", "collect_", "swim_", "climb_shore_", "row_")
HAZARDS = ("death", "kicked")
ENDS = (*HAZARDS, "fatal", "development_trial_ended")  # events after which his loop takes no more actions


class Episode(NamedTuple):
    start: dict[str, int]  # the inventory his agent chose its first action from
    end: dict[str, int]
    steps: list[Transition]
    calls: list[dict[str, Any]]  # planner calls, as model_calls.jsonl records


def read_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def item(name: str) -> str:
    """Wood variants as one item, as the adapter's normalize in craft.mjs."""
    return "log" if name.endswith("_log") else "planks" if name.endswith("_planks") else name


def held(inventory: dict[str, int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for name, n in inventory.items():
        counts[item(name)] += n
    return dict(counts)


def over(inventory: dict[str, int], actions: int, task: Task) -> bool:
    """A grid episode's end: the goal is held or the budget is spent."""
    return inventory.get(task.goal, 0) >= task.count or actions >= task.budget


def parse_action(key: str, description: str) -> tuple[str, str | None, int]:
    """Our action, its target, and how many times the recipe runs, for one menu key."""
    if m := re.fullmatch(r"craft_(\w+?)_(\d+)", key):
        return "craft", item(m[1]), int(m[2])
    if key.startswith(MINES) and (m := re.match(r"Mine and collect one (\w+) at", description)):
        return "mine", item(m[1]), 1
    if key == "place_table":
        return "place", "crafting_table", 1
    if key.startswith(MOVES):
        return "move", key, 1
    return key, None, 1


def episode(events: list[dict[str, Any]], task: Task) -> Episode:
    start = next((held(e["state"]["inventory"]) for e in events if e["type"] == "start"), None)
    if start is None:
        raise ValueError("no start event: not an events.jsonl written by agent.mjs")
    end, decision, hazards, steps, calls = start, None, [], [], []
    for event in events:
        kind = event["type"]
        if kind in ("plan", "plan_error"):
            usage = event.get("usage") or {}
            calls.append({
                "episode": task.task_id, "step": len(steps), "model": event.get("model"), "purpose": "plan",
                "tokens_in": usage.get("prompt_tokens", 0), "tokens_out": usage.get("completion_tokens", 0),
            } | ({"error": event["error"]} if kind == "plan_error" else {}))
        elif kind in HAZARDS:
            hazards.append(kind)
        elif kind == "decision":
            decision, hazards = event, []
            if not steps:
                # The start event precedes the runner's /clear and /give, so the episode starts at the first choice.
                start = end = held(json.loads(event["request"]["state"])["inventory"])
        elif kind == "result":
            after = held(event["inventory"])
            steps.append(_transition(len(steps) + 1, decision, event, end, after, hazards, task.task_id))
            end = after
            if over(end, len(steps), task):
                break
    return Episode(start, end, steps, calls)


def _transition(n: int, decision: dict, result: dict, before: dict, after: dict, hazards: list[str], episode_id: str) -> Transition:
    action, target, times = parse_action(decision["selected"], result["action"])
    rule = BUNDLED.get((action, target))
    predicted = {k: v * times for k, v in rule.delta.items()} if rule else {}
    observed = diff(before, after)
    # Our table has no recipe for stone_axe or oak_boat, so such a craft predicts nothing and is no evidence.
    cls = "ignored" if action == "craft" and rule is None else classify(action, target)
    ok = not result["result"].startswith("FAILED")
    return Transition(
        episode_id, n, SERVER, hashlib.sha256(decision["request"]["state"].encode()).hexdigest()[:12], action, target,
        f"bundled:{rule.rule_id}" if rule else None, predicted, observed, cls,
        verdict(cls, predicted, observed, ok, hazards), ok=ok, events=list(hazards),
    )


def convert(events_path: Path, out_dir: Path, task: Task, change: str | None = None) -> Path:
    """Write manifest.json, <task id>.jsonl and model_calls.jsonl for system B into a new `out_dir`."""
    events = read_events(events_path)
    ep = episode(events, task)
    out_dir.mkdir(parents=True)
    log = TransitionLog(out_dir / f"{task.task_id}.jsonl")
    for t in ep.steps:
        log.append(t)
    (out_dir / "model_calls.jsonl").write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in ep.calls), encoding="utf-8")
    success = ep.end.get(task.goal, 0) >= task.count
    ended = [e["type"] for e in events if e["type"] in ENDS]
    entry = {
        "id": task.task_id, "task": task.task_id, "server": SERVER, "change": change, "seed": None,
        "goal": task.goal, "count": task.count, "inventory": ep.start, "success": success, "actions": len(ep.steps),
        "reason": "goal" if success else "budget" if len(ep.steps) >= task.budget else (ended or ["unfinished"])[-1],
    }
    (out_dir / "manifest.json").write_text(json.dumps({"system": "B", "episodes": [entry]}, indent=2) + "\n", encoding="utf-8")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.convert_rmalde", description="Write system B's run directory from rmalde/minecraft-agent's events.jsonl.")
    parser.add_argument("events", type=Path, help="his runs/<run>/events.jsonl")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--change", help="id of the change loaded on the server, recorded in the manifest")
    args = parser.parse_args()
    try:
        print(convert(args.events, args.out_dir, TASKS[args.task], args.change))
    except ValueError as err:
        raise SystemExit(f"breach.convert_rmalde: {err}")


if __name__ == "__main__":
    main()
