from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable

from .rules import TOOL_TIERS, Rule

UNKNOWN_DISTANCE = 16


@dataclass(frozen=True)
class Step:
    rule_id: str
    action: str
    target: str
    delta: dict[str, int]
    near: str | None
    tool: str | None
    test: bool = False


def plan(goal: str, count: int, inventory: dict[str, int], rules: list[Rule], distance: Callable[[str], int | None]) -> list[Step] | None:
    """Minimum-action plan to hold `count` of `goal`, or None when no certified rule chain produces it.

    ponytail: greedy per item (cheapest producer, prerequisites ordered deepest first, spent inputs
    made again); exact search if competing inputs make greedy plans measurably longer than minimal.
    """
    producers: dict[str, list[Rule]] = {}
    for rule in rules:
        for item in rule.outputs:
            producers.setdefault(item, []).append(rule)
    held = Counter(inventory)
    steps: list[Step] = []

    def best(item: str, seen: frozenset[str] = frozenset()) -> tuple[float, Rule] | None:
        """Cheapest producer of one unit of `item` and its cost, or None when nothing certified makes it."""
        if item in seen:
            return None
        choice = None
        for rule in producers.get(item, ()):
            travel = distance(rule.target) if rule.action == "mine" else 0
            cost: float | None = 1.0 + (UNKNOWN_DISTANCE if travel is None else travel)
            for inp, n in rule.inputs.items():
                sub = best(inp, seen | {item})
                if sub is not None:
                    cost += n * sub[0]
                elif held[inp] < n:  # nothing makes it, though what is held can still be spent
                    cost = None
                    break
            if cost is not None and (choice is None or cost / rule.outputs[item] < choice[0]):
                choice = (cost / rule.outputs[item], rule)
        return choice

    def depth(item: str, seen: frozenset[str] = frozenset()) -> int:
        choice = best(item, seen)
        if choice is None:
            return 0
        return 1 + max((depth(i, seen | {item}) for i in choice[1].inputs), default=0)

    def held_tier() -> int:
        return max((tier for tool, tier in TOOL_TIERS.items() if tool and held[tool] > 0), default=0)

    def ensure(item: str, needed: int, pending: frozenset[str] = frozenset()) -> bool:
        while held[item] < needed:
            choice = best(item)
            # `best` only sees inputs; a station or tool that needs the item being made is a cycle.
            if choice is None or item in pending:
                return False
            rule, inner = choice[1], pending | {item}
            if rule.action == "craft" and rule.near and not ensure(rule.near, 1, inner):
                return False
            if rule.tool and TOOL_TIERS[rule.tool] > held_tier() and not ensure(rule.tool, 1, inner):
                return False
            for inp, n in sorted(rule.inputs.items(), key=lambda kv: depth(kv[0]), reverse=True):
                if not ensure(inp, n, inner):
                    return False
            if any(held[inp] < n for inp, n in rule.inputs.items()):
                continue  # making a later input spent an earlier one
            held.update(rule.delta)
            steps.append(Step(rule.rule_id, rule.action, rule.target, dict(rule.delta), rule.near, rule.tool, rule.status != "certified"))
        return True

    return steps if ensure(goal, count) else None
