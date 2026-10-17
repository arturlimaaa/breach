"""Bounded recovery of a refuted rule: induce revisions, test the cheapest first, keep the first that passes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from itertools import count
from typing import TYPE_CHECKING

from .certify import certify, demote
from .log import Transition
from .planner import Step, plan
from .rules import Rule
from .select import order_tests
from .world import Action

if TYPE_CHECKING:
    from .loop import Executor

Induce = Callable[[Rule, Transition, list[Transition]], list[Rule]]
K = 3
ROUNDS = 2


def recover(ex: Executor, rule: Rule, counterexample: Transition) -> str | None:
    """Rounds of at most K candidates for the demoted `rule`, at most ROUNDS per key and episode.

    A string ends the episode. None lets the executor replan: with the revision as a hypothesis, with the
    untested candidates of a round the budget cut short, or with the rule unknown after the last round.
    """
    server = ex.world.server
    while ex.rounds[rule.key] < ROUNDS:
        ex.rounds[rule.key] += 1
        fresh = (f"{rule.rule_id}#{n}" for n in count(1) if f"{rule.rule_id}#{n}" not in ex.store.rules)
        # The bookkeeping is ours whatever the inducer returns: a global candidate would plan on every server.
        candidates = [
            replace(c, rule_id=next(fresh), status="hypothesis", scope=server, revision_of=rule.rule_id)
            for c in ex.induce(rule, counterexample, [t for t in ex.log if t.episode == ex.episode])[:K]
        ]
        for candidate in candidates:
            ex.store.add(candidate)
        for candidate in order_tests(candidates, ex.observe().inventory):
            t = _test(ex, candidate)
            if isinstance(t, str):
                return t
            if t is None and ex.world.done:
                return None
            if t is not None and t.ok and t.verdict == "match":
                certify(ex.store, ex.log, candidate.rule_id)
                for other in candidates:
                    if other.rule_id != candidate.rule_id:
                        demote(ex.store, other.rule_id, server)
                return None
            # ponytail: a quarantined test counts as failed; retest it if hazards make that common.
            demote(ex.store, candidate.rule_id, server)
    ex.unknown.append(f"{rule.action}:{rule.target}")
    return None


def _test(ex: Executor, candidate: Rule) -> Transition | str | None:
    """Probe a craft candidate's grid, or mine its block once. None when no test ran: the budget ran out or no certified plan makes the grid."""
    if ex.world.done:
        return None
    if candidate.action == "mine":
        # ponytail: the refuted mine just ran with its tool and the grid never consumes tools; acquire candidate.tool once a world can.
        if not ex.travel_to(candidate.target) or ex.world.done:
            return None
        step = Step(candidate.rule_id, "mine", candidate.target, dict(candidate.delta), candidate.near, candidate.tool, test=True)
        return ex.act(Action("mine"), step)[0]
    needs = {**candidate.inputs, **({candidate.near: 1} if candidate.near else {})}
    while True:
        held = ex.observe().inventory
        missing = [item for item, n in needs.items() if held.get(item, 0) < n]
        if not missing:
            break
        steps = plan(missing[0], needs[missing[0]], held, ex.store.usable(ex.world.server), ex.distance)
        if steps is None:
            return None
        hit = ex.execute(steps)
        if isinstance(hit, Transition):
            demote(ex.store, hit.rule_id, ex.world.server)
            return f"contradiction at {hit.rule_id} while testing {candidate.rule_id}"
        if hit is not None or ex.world.done:
            return hit
    step = Step(candidate.rule_id, "probe", candidate.target, candidate.outputs, candidate.near, candidate.tool, test=True)
    return ex.act(Action("probe", candidate.target, grid=candidate.inputs), step)[0]
