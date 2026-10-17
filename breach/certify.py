from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from .log import Transition, TransitionLog, verdict
from .rules import Rule
from .store import RuleStore


@dataclass(frozen=True)
class Certification:
    rule: Rule
    reason: str


def confirmations(log: Iterable[Transition], rule: Rule) -> list[Transition]:
    return [t for t in log if t.rule_id == rule.rule_id and t.verdict == "match" and not t.test]


def contradictions(log: TransitionLog, rule: Rule) -> list[Transition]:
    return [t for t in log.contradictions() if t.rule_id == rule.rule_id]


def certify(store: RuleStore, log: TransitionLog, rule_id: str) -> Certification:
    """A failed certification leaves the stored rule as it is; only `demote` takes a rule out of planning."""
    rule = store.rules[rule_id]
    against, confirmed = contradictions(log, rule), confirmations(log, rule)
    if against:
        return Certification(rule, f"contradicted at {against[0].episode}/{against[0].step}")
    if len(confirmed) < 2:
        return Certification(rule, f"needs 2 confirmations, has {len(confirmed)}")
    if len({t.episode for t in confirmed}) < 2:
        return Certification(rule, f"every confirmation is from episode {confirmed[0].episode}")
    rule = replace(rule, status="certified", evidence=tuple(f"{t.episode}/{t.step}" for t in confirmed))
    store.add(rule)
    return Certification(rule, "certified")


def demote(store: RuleStore, rule_id: str, server: str) -> Rule:
    """Demote on `server` only. A rule from another scope gets a demoted copy here, which shadows it on this server."""
    rule = store.rules[rule_id]
    if rule.scope != server:
        rule = replace(rule, rule_id=f"{rule_id}@{server}", scope=server, revision_of=rule_id)
    rule = replace(rule, status="demoted")
    store.add(rule)
    return rule


def replay(log: Iterable[Transition]) -> list[str]:
    return [verdict(t.cls, t.predicted, t.observed, t.ok, t.events) for t in log]
