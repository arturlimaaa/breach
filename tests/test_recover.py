import json
import unittest
from functools import partial

import breach.induce
from breach.baseline_b import immediate_repeat_rate
from breach.certify import demote, replay
from breach.changes import apply, benchmark, enumerate_class
from breach.log import TransitionLog
from breach.loop import run_episode, run_episode_c
from breach.planner import plan
from breach.rules import Rule
from breach.tasks import T1, T2
from breach.world import VANILLA, GridWorld, Task, rules_from_ruleset
from tests.test_loop import certified_store

STICK_SERVER = "grid/stick-count-2"
DEMOTED_STICK = f"craft:stick@{STICK_SERVER}"
SWAPPED_STICK = "craft:stick@grid/stick-swap-planks-log"
STICKS = Task("hc", "stick", count=4)


def change_world(change_id, task, seed=1):
    change = next(c for c in enumerate_class() if c.id == change_id)
    return GridWorld(task, seed, apply(change, VANILLA), server=f"grid/{change_id}")


def recording(answer):
    """Inducer that answers `answer(rule)`, or raises it when it is an exception, and records each call as (rule, counterexample, tail)."""
    calls = []

    def induce(rule, counterexample, tail):
        calls.append((rule, counterexample, tail))
        reply = answer(rule)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return induce, calls


def scripted(*rounds):
    answers = iter(rounds)
    return recording(lambda rule: next(answers))


def perfect(world):
    """Inducer that answers with the world's own rule for the refuted key."""
    truth = {rule.key: rule for rule in rules_from_ruleset(world.ruleset)}
    return recording(lambda rule: [truth[rule.key]])


def sticks(n, grid=None):
    """A candidate that makes n sticks from `grid`, two planks unless given."""
    return Rule("any", "craft", "stick", {**{item: -k for item, k in (grid or {"planks": 2}).items()}, "stick": n})


def reuses_refuted_rule(log):
    """The first step after the first contradiction that is neither a move nor a look plans from the refuted rule again."""
    first = log.contradictions()[0]
    after = [t for t in log if t.episode == first.episode and t.step > first.step and t.action not in ("move", "look")]
    return bool(after) and after[0].rule_id == first.rule_id


class Slippery(GridWorld):
    """Its first mine fails, as a live server's can when the bot misses the block."""

    missed = False

    def _mine(self, action):
        if self.missed:
            return super()._mine(action)
        self.missed = True
        return self._result(False, "missed the block")


def true_delta(change):
    rule_id = f"mine:{change.block}" if change.kind == "drop" else f"craft:{change.recipe}"
    return next(r.delta for r in rules_from_ruleset(apply(change, VANILLA)) if r.rule_id == rule_id)


def gate(change, goal, seed=1, budget=350):
    """HC on one change world, then HS with the same goal on the same store and server, as the matrix runs them; the inducer is perfect."""
    store, log = certified_store(), TransitionLog()
    world = GridWorld(Task("hc", goal, budget=budget), seed, apply(change, VANILLA), server=f"grid/{change.id}")
    induce, calls = perfect(world)
    hc = run_episode(world, store, log, "hc", induce=induce)
    hc_calls = len(calls)
    hs = run_episode(GridWorld(Task("hs", goal, budget=budget), seed, world.ruleset, server=world.server), store, log, "hs", induce=induce)
    hc_log = TransitionLog()
    for t in log:
        if t.episode == "hc":
            hc_log.append(t)
    first = hc_log.contradictions()[0]
    return {
        "recovered": hc.success, "after": hc.actions - first.step, "repeat": reuses_refuted_rule(hc_log),
        "tests": sum(t.test and "#" in t.rule_id for t in hc_log), "hc_calls": hc_calls, "hs_calls": len(calls) - hc_calls, "hs": hs.reason,
        "hs_contradictions": len(log.contradictions()) - len(hc_log.contradictions()),
        "certified": [r.delta for r in store.usable(world.server) if r.key == (first.action, first.target)],
    }


class RecoveryTests(unittest.TestCase):
    def test_a_refuting_craft_that_succeeded_decides_the_candidates_without_a_probe(self):
        log, store = TransitionLog(), certified_store()
        induce, calls = scripted([sticks(3), sticks(2)])
        result = run_episode(change_world("stick-count-2", STICKS), store, log, "hc", induce=induce)
        [contradiction] = log.contradictions()
        # Bound: no test action, since the refuting craft already ran what each candidate predicts; then the replanned craft.
        after = [(t.action, t.rule_id, t.test, t.predicted, t.observed, t.verdict) for t in log if t.step > contradiction.step]
        self.assertEqual(
            (result.reason, len(calls), after, store.rules[f"{DEMOTED_STICK}#1"].status, reuses_refuted_rule(log), replay(log)),
            (
                "goal", 1, [("craft", DEMOTED_STICK, True, {"planks": -2, "stick": 2}, {"planks": -2, "stick": 2}, "match")],
                "demoted", False, [t.verdict for t in log],
            ),
        )

    def test_a_failed_refuting_craft_is_settled_by_probes_then_the_revision_plans_as_a_test_step(self):
        log = TransitionLog()
        induce, calls = scripted([sticks(3), sticks(4, {"log": 2})])
        result = run_episode(change_world("stick-swap-planks-log", STICKS), certified_store(), log, "hc", induce=induce)
        [contradiction] = log.contradictions()
        # Bound: one probe per grid (at most 3 per round), the inputs a probe needs, then the replanned craft.
        after = [(t.action, t.rule_id, t.test, t.verdict) for t in log if t.step > contradiction.step and t.action not in ("move", "look")]
        self.assertEqual(
            (result.reason, len(calls), after, immediate_repeat_rate(log), replay(log)),
            (
                "goal", 1,
                [
                    ("probe", f"{SWAPPED_STICK}#1", True, "mismatch"),
                    ("mine", "mine:log", False, "match"),
                    ("mine", "mine:log", False, "match"),
                    ("probe", f"{SWAPPED_STICK}#2", True, "match"),
                    ("craft", SWAPPED_STICK, True, "match"),
                ],
                0.0, [t.verdict for t in log],
            ),
        )

    def test_the_next_task_on_the_server_certifies_the_revision_at_first_use_without_the_inducer(self):
        store, log = certified_store(), TransitionLog()
        induce, calls = scripted([sticks(3), sticks(2)])
        run_episode(change_world("stick-count-2", STICKS), store, log, "hc", induce=induce)
        result = run_episode(change_world("stick-count-2", T1), store, log, "hs", induce=induce)
        revision = store.rules[DEMOTED_STICK]
        first_use = next(t for t in log if t.episode == "hs" and t.target == "stick")
        self.assertEqual(
            (
                result.reason, len(calls), [t for t in log.contradictions() if t.episode == "hs"],
                first_use.test, revision.status, revision.evidence[-1], {e.split("/")[0] for e in revision.evidence},
            ),
            ("goal", 1, [], True, "certified", f"hs/{first_use.step}", {"hc", "hs"}),
        )

    def test_two_rounds_of_wrong_candidates_leave_the_rule_unrecovered_and_the_global_rule_planning_elsewhere(self):
        store, log = certified_store(), TransitionLog()
        induce, calls = scripted(
            [sticks(3), sticks(4, {"planks": 3}), sticks(2, {"planks": 1})],
            [sticks(5), sticks(4, {"planks": 4}), sticks(1, {"planks": 3})],
        )
        result = run_episode(change_world("stick-swap-planks-log", STICKS), store, log, "hc", induce=induce)
        probes = [t for t in log if t.action == "probe"]
        vanilla = plan("stick", 4, {}, store.usable("grid/vanilla"), lambda block: 1)
        kept = sorted((r.rule_id, r.status) for r in store.rules.values() if r.scope == "grid/stick-swap-planks-log")
        # Round 2 probes only its new grid: round 1's probes already judge the grids it repeats.
        self.assertEqual(
            (result.reason, len(calls), len(probes), all(p in calls[1][2] for p in probes[:3]), [s.rule_id for s in vanilla], kept),
            (
                "unrecoverable craft:stick", 2, 4, True, ["mine:log", "craft:planks", "craft:stick"],
                [(SWAPPED_STICK, "demoted")] + [(f"{SWAPPED_STICK}#{n}", "demoted") for n in range(1, 7)],
            ),
        )

    def test_a_failed_inducer_call_is_a_failed_round_and_names_the_error_when_nothing_recovers(self):
        outcomes = []
        for rounds in ((RuntimeError("HTTP 503"), RuntimeError("HTTP 503")), (RuntimeError("HTTP 503"), [sticks(2)])):
            induce, calls = scripted(*rounds)
            result = run_episode(change_world("stick-count-2", STICKS), certified_store(), TransitionLog(), "hc", induce=induce)
            outcomes.append((result.reason, len(calls)))
        self.assertEqual(outcomes, [("inducer error: HTTP 503", 2), ("goal", 2)])

    def test_a_contradicting_craft_that_meets_the_goal_reports_success(self):
        world = change_world("furnace-count-2", Task("hc", "furnace", budget=350))
        result = run_episode(world, certified_store(), TransitionLog(), "hc")
        self.assertEqual((result.success, result.reason), (True, "contradiction at craft:furnace"))

    def test_a_contradiction_that_meets_the_goal_still_leaves_a_revision_for_the_next_task(self):
        store, log = certified_store(), TransitionLog()
        world = change_world("furnace-count-2", Task("hc", "furnace", budget=350))
        induce, calls = perfect(world)
        hc = run_episode(world, store, log, "hc", induce=induce)
        [contradiction] = log.contradictions()
        record = store.rules["craft:furnace@grid/furnace-count-2"]
        after_hc = (record.status, record.delta)
        hs = run_episode(change_world("furnace-count-2", Task("hs", "furnace", budget=350)), store, log, "hs", induce=induce)
        # A probe would need 8 more cobblestone; the refuting craft already showed what the revision predicts.
        self.assertEqual(
            (hc.success, hc.actions - contradiction.step, after_hc, len(calls), hs.success, store.rules[record.rule_id].status),
            (True, 0, ("hypothesis", {"cobblestone": -8, "furnace": 2}), 1, True, "certified"),
        )

    def test_the_production_inducer_wiring_recovers_through_its_schema_gate(self):
        replies = []

        def complete(messages, **kwargs):
            replies.append(kwargs["purpose"])
            return json.dumps([{"action": "craft", "target": "stick", "delta": {"planks": -2, "stick": 2}, "tool": None, "near": None}])

        store = certified_store()
        induce = partial(breach.induce.induce, complete=complete)
        result = run_episode(change_world("stick-count-2", STICKS), store, TransitionLog(), "hc", induce=induce)
        self.assertEqual((result.reason, replies, store.rules[DEMOTED_STICK].delta), ("goal", ["induce"], {"planks": -2, "stick": 2}))

    def test_candidates_the_budget_left_untested_are_tested_by_the_next_task_without_the_inducer(self):
        probe = TransitionLog()
        run_episode(change_world("stick-swap-planks-log", STICKS), certified_store(), probe, "hc")
        refuted_at = probe.contradictions()[0].step
        store, log = certified_store(), TransitionLog()
        induce, calls = scripted([sticks(3), sticks(4, {"log": 2})])
        run_episode(change_world("stick-swap-planks-log", Task("hc", "stick", count=4, budget=refuted_at)), store, log, "hc", induce=induce)
        result = run_episode(change_world("stick-swap-planks-log", STICKS), store, log, "hs", induce=induce)
        tests = [(t.episode, t.rule_id, t.verdict) for t in log if t.test]
        record = store.rules[SWAPPED_STICK]
        self.assertEqual(
            (result.reason, len(calls), tests, record.status, record.delta),
            (
                "goal", 1, [("hs", f"{SWAPPED_STICK}#1", "mismatch"), ("hs", f"{SWAPPED_STICK}#2", "match")],
                "hypothesis", {"log": -2, "stick": 4},
            ),
        )

    def test_a_candidate_no_certified_plan_can_make_the_grid_for_is_dropped_untested(self):
        log = TransitionLog()
        untestable = Rule("any", "craft", "stick", {"planks": -2, "diamond": -1, "stick": 4})
        induce, calls = scripted([untestable], [sticks(4, {"log": 2})])
        result = run_episode(change_world("stick-swap-planks-log", STICKS), certified_store(), log, "hc", induce=induce)
        self.assertEqual(
            (result.reason, len(calls), [t.rule_id for t in log if t.action == "probe"]),
            ("goal", 2, [f"{SWAPPED_STICK}#2"]),
        )

    def test_a_contradiction_while_acquiring_a_grid_ends_the_episode_with_a_reason(self):
        changed = {c.id: c for c in enumerate_class()}
        ruleset = apply(changed["stone-drop-nothing"], apply(changed["torch-add-cobblestone"], VANILLA))
        world, store = GridWorld(Task("hc", "torch", budget=300), 1, ruleset, server="grid/two"), certified_store()
        result = run_episode(world, store, TransitionLog(), "hc", induce=perfect(world)[0])
        self.assertEqual(
            (result.reason, store.rules["mine:stone@grid/two"].status),
            ("contradiction at mine:stone while testing craft:torch@grid/two#1", "demoted"),
        )

    def test_an_unrecovered_rule_is_routed_around_when_what_it_made_is_held(self):
        log = TransitionLog()
        induce, calls = scripted([sticks(3)], [sticks(5)])
        result = run_episode(change_world("stick-count-2", T1), certified_store(), log, "hc", induce=induce)
        self.assertEqual((result.reason, len(calls), [t.target for t in log if t.action == "craft"][-1]), ("goal", 2, "wooden_pickaxe"))

    def test_a_drop_change_is_revised_from_the_refuting_mine(self):
        cases = [
            ("stone-drop-nothing", T2, "mine:stone", {}, "no certified plan", []),
            ("coal_ore-drop-cobblestone", Task("hc", "torch", budget=300), "mine:coal_ore", {"cobblestone": 1}, "no certified plan", []),
            ("log-drop-planks", Task("hc", "stick"), "mine:log", {"planks": 1}, "goal", [("mine", {"planks": 1}, {"planks": 1}, "match")]),
        ]
        for change_id, task, rule_id, drop, reason, tests in cases:
            with self.subTest(change_id):
                world, log, store = change_world(change_id, task), TransitionLog(), certified_store()
                result = run_episode(world, store, log, "hc", induce=perfect(world)[0])
                record = store.rules[f"{rule_id}@{world.server}"]
                self.assertEqual(
                    (result.reason, record.delta, record.status, [(t.action, t.predicted, t.observed, t.verdict) for t in log if t.test]),
                    (reason, drop, "hypothesis", tests),
                )

    def test_a_failed_refuting_mine_is_settled_by_one_mine_test(self):
        log, store = TransitionLog(), certified_store()
        world = Slippery(Task("p", "planks"), seed=1, server="grid/slippery")
        result = run_episode(world, store, log, "p", induce=perfect(world)[0])
        self.assertEqual(
            (result.reason, [(t.action, t.rule_id, t.observed, t.verdict) for t in log if t.test], store.rules["mine:log@grid/slippery"].delta),
            ("goal", [("mine", "mine:log@grid/slippery#1", {"log": 1}, "match")], {"log": 1}),
        )

    def test_a_failed_test_step_demotes_only_its_hypothesis_and_counts_as_a_counterexample(self):
        store, log = certified_store(), TransitionLog()
        demote(store, "craft:stick", STICK_SERVER)
        wrong = Rule(f"{DEMOTED_STICK}#1", "craft", "stick", {"planks": -2, "stick": 3}, scope=STICK_SERVER, revision_of=DEMOTED_STICK)
        store.add(wrong)
        certified = {r.rule_id for r in store.rules.values() if r.status == "certified"}
        world = change_world("stick-count-2", STICKS)
        induce, calls = perfect(world)
        result = run_episode(world, store, log, "hs", induce=induce)
        self.assertEqual(
            (
                result.reason, log.contradictions(), store.rules[wrong.rule_id].status, calls[0][0].rule_id, calls[0][1].rule_id,
                {r.rule_id for r in store.rules.values() if r.status == "certified"},
            ),
            ("goal", [], "demoted", DEMOTED_STICK, wrong.rule_id, certified),
        )

    def test_a_certified_plan_is_preferred_over_a_cheaper_hypothesis(self):
        store, log = certified_store(), TransitionLog()
        store.add(Rule("mine:stone#1", "mine", "stone", {"planks": 64}, scope="grid/x"))
        cheaper = plan("planks", 1, {}, store.usable("grid/x", hypotheses=True), lambda block: 1)
        result = run_episode(GridWorld(Task("p", "planks"), seed=1, server="grid/x"), store, log, "p")
        self.assertEqual(
            ([(s.rule_id, s.test) for s in cheaper], result.reason, [t for t in log if t.test]),
            ([("mine:stone#1", True)], "goal", []),
        )


class SystemCTests(unittest.TestCase):
    def test_c_repeats_the_refuted_craft_and_d_crafts_from_the_revision(self):
        c_log, d_log = TransitionLog(), TransitionLog()
        run_episode_c(change_world("stick-count-2", STICKS), certified_store(), c_log, "c")
        world = change_world("stick-count-2", STICKS)
        run_episode(world, certified_store(), d_log, "d", induce=perfect(world)[0])
        self.assertEqual(
            (immediate_repeat_rate(c_log) > 0, reuses_refuted_rule(c_log), reuses_refuted_rule(d_log)),
            (True, True, False),
        )


class GridGateTests(unittest.TestCase):
    def test_every_benchmark_change_recovers_within_the_bound_and_its_next_task_calls_no_inducer(self):
        rows = {change.id: gate(change, goal) for change, goal in benchmark()}
        truth = {change.id: true_delta(change) for change, _ in benchmark()}
        verdicts = {
            change_id: (
                r["recovered"], r["repeat"], 1 <= r["hc_calls"] <= 2, r["tests"] <= 6,
                r["hs_calls"], r["hs"], r["hs_contradictions"], r["certified"],
            )
            for change_id, r in rows.items()
        }
        self.assertEqual(verdicts, {change_id: (True, False, True, True, 0, "goal", 0, [truth[change_id]]) for change_id in rows})


if __name__ == "__main__":
    unittest.main()
