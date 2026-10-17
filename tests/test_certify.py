import unittest
from dataclasses import replace

from breach.certify import Certification, certify, demote, replay
from breach.log import Transition, TransitionLog, verdict
from breach.rules import Rule
from breach.store import RuleStore

STICK = Rule("craft:stick", "craft", "stick", {"planks": -2, "stick": 4})


def crafted(episode, step, sticks=4, test=False, events=(), rule_id=STICK.rule_id):
    observed = {"planks": -2, "stick": sticks}
    return Transition(
        episode, step, "grid/vanilla", "", "craft", "stick", rule_id, STICK.delta, observed, "exact",
        verdict("exact", STICK.delta, observed, True, events), test, events=list(events),
    )


def certifying(*transitions):
    store, log = RuleStore(), TransitionLog()
    store.add(STICK)
    for transition in transitions:
        log.append(transition)
    return certify(store, log, STICK.rule_id), store.rules[STICK.rule_id]


class CertifyTests(unittest.TestCase):
    def test_two_confirmations_from_two_episodes_certify_the_rule(self):
        certified = replace(STICK, status="certified", evidence=("t1/3", "t2/7"))
        self.assertEqual(
            certifying(crafted("t1", 3), crafted("t2", 7)),
            (Certification(certified, "certified"), certified),
        )

    def test_a_contradiction_leaves_the_status_unchanged(self):
        self.assertEqual(
            certifying(crafted("t1", 3), crafted("t2", 7), crafted("hc", 6, sticks=2)),
            (Certification(STICK, "contradicted at hc/6"), STICK),
        )

    def test_one_confirmation_leaves_the_status_unchanged(self):
        self.assertEqual(
            certifying(crafted("t1", 3)),
            (Certification(STICK, "needs 2 confirmations, has 1"), STICK),
        )

    def test_confirmations_from_one_episode_leave_the_status_unchanged(self):
        self.assertEqual(
            certifying(crafted("t1", 3), crafted("t1", 7)),
            (Certification(STICK, "every confirmation is from episode t1"), STICK),
        )

    def test_test_steps_quarantined_steps_and_other_rules_count_neither_way(self):
        self.assertEqual(
            certifying(
                crafted("t1", 3),
                crafted("t2", 7, test=True),
                crafted("t3", 9, sticks=2, events=["despawn"]),
                crafted("t4", 1, rule_id="craft:other"),
                crafted("hc", 6, sticks=2, rule_id="craft:other"),
            ),
            (Certification(STICK, "needs 2 confirmations, has 1"), STICK),
        )


SERVER = "grid/stick-count-2"
REVISION = Rule(
    "craft:stick@grid/stick-count-2#1", "craft", "stick", {"planks": -2, "stick": 2},
    scope=SERVER, source="induced", revision_of="craft:stick@grid/stick-count-2",
)


def stepped(episode, step, action, rule_id, predicted, observed, ok=True, server=SERVER):
    return Transition(
        episode, step, server, "", action, "stick", rule_id, predicted, observed, "exact",
        verdict("exact", predicted, observed, ok), rule_id != STICK.rule_id, ok,
    )


PRE_CHANGE = stepped("e1", 2, "craft", STICK.rule_id, STICK.delta, STICK.delta)
COUNTEREXAMPLE = stepped("e1", 5, "craft", STICK.rule_id, STICK.delta, REVISION.delta)
PROBE = stepped("e1", 6, "probe", REVISION.rule_id, REVISION.outputs, REVISION.outputs)
USE = stepped("e2", 3, "craft", REVISION.rule_id, REVISION.delta, REVISION.delta)


def revising(*transitions, siblings=()):
    store, log = RuleStore(), TransitionLog()
    for rule in (REVISION, *siblings):
        store.add(rule)
    for transition in transitions:
        log.append(transition)
    return certify(store, log, REVISION.rule_id)


def sibling(n, delta):
    return replace(REVISION, rule_id=f"craft:stick@grid/stick-count-2#{n}", delta=delta, status="demoted")


class ReplayCertifyTests(unittest.TestCase):
    def test_a_counterexample_and_a_probe_then_a_use_in_another_episode_certify_a_revision(self):
        certified = replace(REVISION, status="certified", evidence=("e1/5", "e1/6", "e2/3"))
        self.assertEqual(revising(COUNTEREXAMPLE, PROBE, USE), Certification(certified, "certified"))

    def test_a_pre_change_match_on_the_same_server_blocks_a_revision(self):
        self.assertEqual(revising(PRE_CHANGE, COUNTEREXAMPLE, PROBE, USE), Certification(REVISION, "contradicted at e1/2"))

    def test_failed_steps_other_servers_and_other_grids_count_neither_way(self):
        failed = stepped("e1", 4, "craft", STICK.rule_id, STICK.delta, {}, ok=False)
        elsewhere = stepped("e1", 1, "craft", STICK.rule_id, STICK.delta, STICK.delta, server="grid/vanilla")
        swapped = sibling(2, {"log": -2, "stick": 4})
        other_grid = stepped("e1", 7, "probe", swapped.rule_id, swapped.outputs, {})
        certified = replace(REVISION, status="certified", evidence=("e1/6", "e2/3"))
        self.assertEqual(
            revising(elsewhere, failed, PROBE, other_grid, USE, siblings=[swapped]), Certification(certified, "certified"),
        )

    def test_a_probe_logged_under_another_candidate_counts_for_every_rule_with_its_grid(self):
        three = sibling(3, {"planks": -2, "stick": 3})
        probed = stepped("e1", 8, "probe", three.rule_id, three.outputs, REVISION.outputs)
        certified = replace(REVISION, status="certified", evidence=("e1/8", "e2/3"))
        self.assertEqual(revising(probed, USE, siblings=[three]), Certification(certified, "certified"))


class ReplayTests(unittest.TestCase):
    def test_a_failed_move_replays_as_a_mismatch_and_an_unchecked_probe_as_ignored(self):
        move = Transition("t1", 1, "grid/vanilla", "", "move", "up", None, {}, {}, "tolerant", "mismatch", ok=False)
        probe = Transition("t1", 2, "grid/vanilla", "", "probe", "stick", None, {}, {}, "ignored", "ignored")
        self.assertEqual(replay([move, probe]), ["mismatch", "ignored"])


class DemoteTests(unittest.TestCase):
    def test_a_rule_scoped_to_the_server_is_demoted_in_place(self):
        scoped = replace(STICK, rule_id="craft:stick@grid/x", scope="grid/x", status="certified")
        store = RuleStore()
        store.add(scoped)
        demote(store, scoped.rule_id, "grid/x")
        self.assertEqual(store.rules, {scoped.rule_id: replace(scoped, status="demoted")})


if __name__ == "__main__":
    unittest.main()
