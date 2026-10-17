"""Ask the text model for revisions of a contradicted rule; keep only what parses as a rule."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import partial

from .changes import items
from .llm import complete
from .log import Transition
from .rules import ACTIONS, CLASSES, STATUSES, TOOL_TIERS, Rule

_PROPERTIES = {
    "rule_id": {"type": "string"},
    "action": {"enum": list(ACTIONS)},
    "target": {"type": "string"},
    "delta": {"type": "object", "additionalProperties": {"type": "integer"}},
    "tool": {"enum": list(TOOL_TIERS)},
    "near": {"type": ["string", "null"]},
    "cls": {"enum": list(CLASSES)},
    "status": {"enum": list(STATUSES)},
    "scope": {"type": "string"},
    "source": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}},
    "revision_of": {"type": ["string", "null"]},
}
JSON_SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": _PROPERTIES, "required": list(_PROPERTIES), "additionalProperties": False},
}
_FENCE = re.compile(r"```\w*\s*(.*?)```", re.DOTALL)
STATIONS = ("crafting_table", "furnace")


def induce(
    rule: Rule, counterexample: Transition, log_tail: list[Transition], *, k: int = 3, complete: Callable[..., str] = complete
) -> list[Rule]:
    """At most k hypotheses revising `rule` on the counterexample's server, from one call and at most one retry."""
    ask = partial(
        complete, schema=JSON_SCHEMA, thinking=True,
        episode=counterexample.episode, step=counterexample.step, purpose="induce",
    )
    messages = [{"role": "user", "content": _prompt(rule, counterexample, log_tail, k)}]
    reply = ask(messages)
    candidates, errors = _gate(reply, rule, counterexample.server, k)
    if candidates:
        return candidates
    feedback = f"No usable rule in that reply: {'; '.join(errors) or 'the array was empty'}. Reply with only the JSON array."
    retry = [*messages, {"role": "assistant", "content": reply}, {"role": "user", "content": feedback}]
    return _gate(ask(retry), rule, counterexample.server, k)[0]


def _gate(reply: str, rule: Rule, server: str, k: int) -> tuple[list[Rule], list[str]]:
    """Rule objects in `reply` that parse and revise `rule`, distinct by delta, at most k; plus why the others failed."""
    fenced = _FENCE.search(reply)
    try:
        items = json.loads(fenced.group(1) if fenced else reply)
    except ValueError as exc:
        return [], [f"not JSON ({exc})"]
    if not isinstance(items, list):
        return [], ["the reply must be a JSON array of rule objects"]
    kept: list[Rule] = []
    errors: list[str] = []
    for n, item in enumerate(items, 1):
        try:
            # Bookkeeping is ours: an echoed rule_id would replace the global rule in the store,
            # and cls decides how strictly the step is verified.
            candidate = Rule.parse({
                **item, "rule_id": f"{rule.rule_id}#{len(kept) + 1}", "cls": rule.cls, "status": "hypothesis",
                "scope": server, "source": "induced", "evidence": [], "revision_of": rule.rule_id,
            })
            if candidate.key != rule.key:
                raise ValueError(f"action and target must stay {rule.action} {rule.target}")
            if candidate.action == "craft":
                # Anything else can neither be tested by a probe nor planned: an empty grid always shows an empty slot.
                if candidate.delta.get(candidate.target, 0) <= 0 or not candidate.inputs:
                    raise ValueError(f"a craft's delta consumes at least one item and produces {candidate.target}")
                if candidate.near not in (None, *STATIONS):
                    raise ValueError(f"near must be null or a station: {', '.join(STATIONS)}")
            elif not isinstance(candidate.near, str | None):
                raise ValueError("near must be a block name or null")
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"item {n}: {exc!r}")
            continue
        if all(c.delta != candidate.delta for c in kept):
            kept.append(candidate)
    return kept[:k], errors


def _prompt(rule: Rule, counterexample: Transition, log_tail: list[Transition], k: int) -> str:
    def j(value: object) -> str:
        return json.dumps(value, sort_keys=True)

    c = counterexample
    steps = [t for t in log_tail if t.action != "move"]
    deltas = [rule.delta, c.predicted, c.observed] + [d for t in steps for d in (t.predicted, t.observed)]
    in_play = sorted({item for delta in deltas for item in delta})
    recent = "\n".join(f"- {t.action} {t.target}: predicted {j(t.predicted)}, observed {j(t.observed)}, {t.verdict}" for t in steps)
    # The gate's own constraints, so the model is not refused for what it was never told.
    craft = (
        f"\nA craft's delta lists every item it consumes as a negative count and {rule.target} as a positive count; "
        f'near is null, "crafting_table" or "furnace"; tool is null or one of {", ".join(t for t in TOOL_TIERS if t)}.'
    ) if rule.action == "craft" else ""
    return f"""Server {c.server} contradicted a rule the agent had certified.

Rule: {j(rule.to_dict())}
Step {c.episode}/{c.step}: {c.action} {c.target} predicted {j(c.predicted)} but observed {j(c.observed)}.
Deltas are inventory changes: negative is consumed, positive is produced. An empty delta means nothing changed.
The server differs from vanilla in exactly one rule, changed in one way: a recipe's output count, one ingredient added to a recipe, one ingredient swapped for another, or a block's drop changed or removed.

Recent steps:
{recent or "- none"}

Items in play: {", ".join(in_play)}. Every item in this world: {", ".join(items())}. Use these generic names.
A probe reports the output slot for a placed grid at no cost, so every candidate will be tested.

Propose at most {k} revisions of the rule that explain the observation, most likely first.
Reply with only a JSON array of rule objects with the rule's fields. Keep action "{rule.action}" and target "{rule.target}".
Set status "hypothesis", scope "{c.server}", source "induced", revision_of "{rule.rule_id}", evidence [],
and rule_id "{rule.rule_id}#1", "{rule.rule_id}#2", and so on.
Express every precondition through delta, tool, or near; free-text preconditions are rejected.{craft}"""
