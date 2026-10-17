"""Bounded recovery of a refuted rule: induce revisions, judge each from the log or else by the cheapest test, and
move the first that passes into the server's record of the rule, the copy `certify.demote` made."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from itertools import count
from time import perf_counter
from typing import TYPE_CHECKING

from .certify import certify, demote, replayed
from .log import Transition
from .planner import Step, plan
from .rules import Rule
from .select import order_tests
from .status import change, shown
from .store import RuleStore
from .world import Action

if TYPE_CHECKING:
    from .loop import Executor

Induce = Callable[[Rule, Transition, list[Transition]], list[Rule]]
K = 3
ROUNDS = 2


def recover(ex: Executor, record: Rule, counterexample: Transition) -> str | None:
    """Rounds of at most K candidates for the demoted server `record`, at most ROUNDS per key and episode.

    A string ends the episode. None lets the executor replan: with the revised record as a hypothesis, with the
    untested candidates of a round the budget cut short, or with the rule unrecovered after the last round.
    """
    server = ex.world.server

    def settle(note: str) -> None:
        ex.status.rule = shown(ex.store.rules[record.rule_id], note)
        ex.status.emit(ex)

    while ex.rounds[record.key] < ROUNDS:
        ex.rounds[record.key] += 1
        start = perf_counter()
        # An inducer error ends the run: a broken model must not read as a rule that could not be recovered.
        proposed = ex.induce(record, counterexample, [t for t in ex.log if t.episode == ex.episode])
        ex.status.calls += 1
        ex.status.latency_ms = round((perf_counter() - start) * 1000)
        fresh = (f"{record.rule_id}#{n}" for n in count(1) if f"{record.rule_id}#{n}" not in ex.store.rules)
        # The bookkeeping is ours whatever the inducer returns: a global candidate would plan on every server.
        candidates = [replace(c, rule_id=next(fresh), status="hypothesis", scope=server, revision_of=record.rule_id) for c in proposed[:K]]
        for candidate in candidates:
            ex.store.add(candidate)
        heard = f"{len(candidates)} candidate{'' if len(candidates) == 1 else 's'}"
        ex.status.rule = shown(record, heard, "revising")
        ex.status.emit(ex)
        for candidate in order_tests(candidates, ex.observe().inventory):
            passed = _judged(ex, candidate, counterexample)
            how = "the refuting step" if passed is not None else "a probe"
            ex.status.rule = shown(record, f"{heard}; testing {change(candidate)} by {how}", "revising")
            ex.status.emit(ex)
            if passed is None:
                t = _test(ex, candidate)
                if isinstance(t, str):
                    settle(t)
                    return t
                if t is None and ex.world.done:
                    settle("the budget ran out before every candidate was tested")
                    return None
                passed = t is not None and t.ok and t.cls == "exact" and t.verdict == "match"
            if passed:
                adopt(ex.store, candidate)
                settle(certify(ex.store, ex.log, record.rule_id).reason)
                return None
            # ponytail: a quarantined test counts as failed; retest it if hazards make that common.
            demote(ex.store, candidate.rule_id, server)
    ex.unrecovered.append(f"unrecoverable {record.action}:{record.target}")
    settle(ex.unrecovered[-1])
    return None


def _judged(ex: Executor, candidate: Rule, since: Transition) -> bool | None:
    """What the log says of the candidate from the refuting step on, or None when nothing there tested it.

    A refuting step that succeeded already ran the craft or mine every candidate predicts, and a probe judges
    every candidate with its grid. Steps before the refuting one may predate the change, so they do not count.
    """
    recent = [t for t in ex.log if t.episode == since.episode and t.step >= since.step]
    against, confirmed = replayed(recent, candidate, ex.store.rules)
    if against:
        return False
    return True if confirmed else None


def adopt(store: RuleStore, candidate: Rule) -> Rule:
    """The candidate becomes the record it revises, a hypothesis until certified; every live candidate of that record retires."""
    for rule in [r for r in store.rules.values() if r.revision_of == candidate.revision_of and r.status == "hypothesis"]:
        store.add(replace(rule, status="demoted"))
    record = replace(
        store.rules[candidate.revision_of], delta=dict(candidate.delta), tool=candidate.tool, near=candidate.near,
        status="hypothesis", source=candidate.source, evidence=(),
    )
    store.add(record)
    return record


def _test(ex: Executor, candidate: Rule) -> Transition | str | None:
    """Probe a craft candidate's grid at a station within reach.

    None when no probe ran: the budget ran out, no certified plan makes the grid, or the candidate is a mine, which
    only a refuting mine that removed its block can raise, and that mine already judged it.
    """
    if ex.world.done or candidate.action != "craft":
        return None
    near = candidate.near
    # A station already on the map is walked to, so only a missing one has to be made.
    needs = {**candidate.inputs, **({near: 1} if near and near not in ex.known.values() else {})}
    while True:
        held = ex.observe().inventory
        missing = [item for item, n in needs.items() if held.get(item, 0) < n]
        if not missing:
            break
        steps = plan(missing[0], needs[missing[0]], held, ex.store.usable(ex.world.server), ex.distance, set(ex.known.values()))
        if steps is None:
            return None
        hit = ex.execute(steps)
        if isinstance(hit, Transition):
            demote(ex.store, hit.rule_id, ex.world.server)
            return f"contradiction at {hit.rule_id} while testing {candidate.rule_id}"
        if hit is not None or ex.world.done:
            return hit
    if near and not ex.station(near):
        return None
    step = Step(candidate.rule_id, "probe", candidate.target, candidate.outputs, candidate.near, candidate.tool, test=True)
    return ex.act(Action("probe", candidate.target, grid=candidate.inputs), step)[0]
