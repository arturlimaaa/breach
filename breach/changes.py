from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .planner import Step, plan
from .world import VANILLA, Recipe, Ruleset, rules_from_ruleset

SWAP_ORDER = ("log", "planks", "stick", "cobblestone", "coal")
DROP_SWAPS = {"log": "planks", "stone": "stone", "coal_ore": "cobblestone"}
# Every other generic name is its own vanilla id.
VANILLA_IDS = {"log": "oak_log", "planks": "oak_planks"}


@dataclass(frozen=True)
class Change:
    """One single-rule change. `value` is the new output count, the added inputs, {old: new}, or the new drop."""

    id: str
    kind: str
    recipe: str | None
    block: str | None
    value: int | dict[str, int] | dict[str, str]

    @staticmethod
    def parse(data: dict[str, Any]) -> Change:
        change = Change(str(data["id"]), data["kind"], data.get("recipe"), data.get("block"), data["value"])
        value = change.value
        fits = {
            "count": type(value) is int and value > 0,
            "add_ingredient": _counts(value) and len(value) > 0,
            "swap_ingredient": isinstance(value, dict) and len(value) == 1 and all(isinstance(s, str) for s in (*value, *value.values())),
            "drop": _counts(value),
        }.get(change.kind, False)
        target = change.block if change.kind == "drop" else change.recipe
        if not fits or not isinstance(target, str):
            raise ValueError(f"{change.kind!r} change on {target!r} cannot hold {value!r}")
        return change

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _counts(value: Any) -> bool:
    return isinstance(value, dict) and all(isinstance(k, str) and type(n) is int and n > 0 for k, n in value.items())


def enumerate_class(ruleset: Ruleset = VANILLA) -> list[Change]:
    changes = []
    for name, recipe in ruleset.recipes.items():
        count = 2 if recipe.output == 1 else (recipe.output + 1) // 2
        added = "cobblestone" if "coal" in recipe.inputs else "coal"
        old = next(iter(recipe.inputs))
        new = next(item for item in SWAP_ORDER if item not in recipe.inputs and item != name)
        changes += [
            Change(f"{name}-count-{count}", "count", name, None, count),
            Change(f"{name}-add-{added}", "add_ingredient", name, None, {added: 1}),
            Change(f"{name}-swap-{old}-{new}", "swap_ingredient", name, None, {old: new}),
        ]
    for block in ruleset.drops:
        item = DROP_SWAPS[block]
        changes += [
            Change(f"{block}-drop-{item}", "drop", None, block, {item: 1}),
            Change(f"{block}-drop-nothing", "drop", None, block, {}),
        ]
    return changes


def apply(change: Change, ruleset: Ruleset) -> Ruleset:
    if change.kind == "drop":
        return replace(ruleset, drops={**ruleset.drops, change.block: dict(change.value)})
    recipe = ruleset.recipes[change.recipe]
    if change.kind == "count":
        recipe = replace(recipe, output=change.value)
    elif change.kind == "add_ingredient":
        recipe = replace(recipe, inputs=dict(Counter(recipe.inputs) + Counter(change.value)))
    else:
        [(old, new)] = change.value.items()
        recipe = replace(recipe, inputs={new if item == old else item: n for item, n in recipe.inputs.items()})
    return replace(ruleset, recipes={**ruleset.recipes, change.recipe: recipe})


def _plan(goal: str, ruleset: Ruleset) -> list[Step] | None:
    # A constant travel cost keeps the chosen goal independent of any seed's layout.
    return plan(goal, 1, {}, rules_from_ruleset(ruleset, status="certified"), lambda block: 4)


def goal_for(change: Change, ruleset: Ruleset = VANILLA) -> str | None:
    """Recipe output with the fewest plan steps under the changed rules whose plan uses the changed rule."""
    changed = apply(change, ruleset)
    rule_id = f"mine:{change.block}" if change.kind == "drop" else f"craft:{change.recipe}"
    plans = {goal: _plan(goal, changed) for goal in ruleset.recipes}
    uses = [goal for goal, steps in plans.items() if steps and any(s.rule_id == rule_id for s in steps)]
    return min(uses, key=lambda goal: len(plans[goal]), default=None)


def benchmark(ruleset: Ruleset = VANILLA) -> list[tuple[Change, str]]:
    return [(change, goal) for change in enumerate_class(ruleset) if (goal := goal_for(change, ruleset))]


def write_ruleset(change: Change, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(apply(change, VANILLA)), indent=2) + "\n", encoding="utf-8")


def load_ruleset(path: Path) -> Ruleset:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Ruleset({item: Recipe(**recipe) for item, recipe in data["recipes"].items()}, data["drops"], data["tools"])


def _id(name: str) -> str:
    return VANILLA_IDS.get(name, name)


def write_datapack(change: Change, directory: Path) -> None:
    """Minecraft Java 1.16.5 datapack that overrides the changed recipe or block loot table."""
    changed = apply(change, VANILLA)
    if change.kind == "drop":
        overridden = "none"
        path = f"loot_tables/blocks/{_id(change.block)}.json"
        data = {
            "type": "minecraft:block",
            "pools": [
                {"rolls": 1, "entries": [{"type": "minecraft:item", "name": f"minecraft:{_id(item)}", "functions": [{"function": "minecraft:set_count", "count": n}]}]}
                for item, n in changed.drops[change.block].items()
            ],
        }
    else:
        recipe = changed.recipes[change.recipe]
        overridden = f"minecraft:{_id(change.recipe)}"
        path = f"recipes/{_id(change.recipe)}.json"
        data = {
            "type": "minecraft:crafting_shapeless",
            "ingredients": [{"item": f"minecraft:{_id(item)}"} for item, n in recipe.inputs.items() for _ in range(n)],
            "result": {"item": f"minecraft:{_id(change.recipe)}", "count": recipe.output},
        }
    files = {
        "pack.mcmeta": json.dumps({"pack": {"pack_format": 6, "description": f"breach change {change.id}"}}, indent=2),
        f"data/minecraft/{path}": json.dumps(data, indent=2),
        "data/minecraft/recipes/README.txt": f"Vanilla recipe ids overridden by {change.id}: {overridden}",
    }
    for name, text in files.items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 -m breach.changes <out_dir>")
    out, rows = Path(sys.argv[1]), benchmark()
    print(f"{'change':<36} {'goal':<15} steps")
    for change, goal in rows:
        write_ruleset(change, out / change.id / "ruleset.json")
        write_datapack(change, out / change.id / "datapack")
        print(f"{change.id:<36} {goal:<15} {len(_plan(goal, apply(change, VANILLA)))}")
    included = {change.id for change, _ in rows}
    excluded = [change.id for change in enumerate_class() if change.id not in included]
    print(f"{len(rows)} of {len(rows) + len(excluded)} benchmarked; excluded: {', '.join(excluded)}")
