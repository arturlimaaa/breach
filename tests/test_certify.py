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
