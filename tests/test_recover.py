import unittest

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
STICKS = Task("hc", "stick", count=4)


def change_world(change_id, task, seed=1):
    change = next(c for c in enumerate_class() if c.id == change_id)
    return GridWorld(task, seed, apply(change, VANILLA), server=f"grid/{change_id}")


def recording(answer):
    """Inducer that answers `answer(rule)` and records each call as (rule, counterexample, tail)."""
    calls = []

    def induce(rule, counterexample, tail):
        calls.append((rule, counterexample, tail))
        return answer(rule)

    return induce, calls


def scripted(*rounds):
    answers = iter(rounds)
    return recording(lambda rule: next(answers))


def perfect(world):
    """Inducer that answers with the world's own rule for the refuted key."""
    truth = {rule.key: rule for rule in rules_from_ruleset(world.ruleset)}
    return recording(lambda rule: [truth[rule.key]])


def sticks(n):
    return Rule("any", "craft", "stick", {"planks": -2, "stick": n})


def true_delta(change):
    rule_id = f"mine:{change.block}" if change.kind == "drop" else f"craft:{change.recipe}"
    return next(r.delta for r in rules_from_ruleset(apply(change, VANILLA)) if r.rule_id == rule_id)


def gate(change, goal, seed=1, budget=300):
    """HC on one change world, then HS with the same goal on the same store and server; the inducer is perfect."""
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
        "recovered": hc.success, "after": hc.actions - first.step, "repeat": immediate_repeat_rate(hc_log),
        "tests": sum(t.test and t.action in ("probe", "mine") for t in hc_log), "hc_calls": hc_calls,
        "hs_calls": len(calls) - hc_calls, "hs": hs.reason, "hs_contradictions": len(log.contradictions()) - len(hc_log.contradictions()),
        "certified": [r.delta for r in store.usable(world.server) if r.key == (first.action, first.target)],
    }


class RecoveryTests(unittest.TestCase):
    def test_a_wrong_then_right_revision_is_probed_then_planned_as_a_test_step(self):
        log = TransitionLog()
        induce, calls = scripted([sticks(3), sticks(2)])
        result = run_episode(change_world("stick-count-2", STICKS), certified_store(), log, "hc", induce=induce)
        [contradiction] = log.contradictions()
        # Bound: one probe per candidate (at most 3 per round), then the replanned craft.
        after = [(t.action, t.rule_id, t.test, t.predicted, t.observed, t.verdict) for t in log if t.step > contradiction.step]
        self.assertEqual(
            (result.reason, len(calls), after, immediate_repeat_rate(log), replay(log)),
            (
                "goal", 1,
                [
                    ("probe", f"{DEMOTED_STICK}#1", True, {"stick": 3}, {"stick": 2}, "mismatch"),
                    ("probe", f"{DEMOTED_STICK}#2", True, {"stick": 2}, {"stick": 2}, "match"),
                    ("craft", f"{DEMOTED_STICK}#2", True, {"planks": -2, "stick": 2}, {"planks": -2, "stick": 2}, "match"),
                ],
                0.0, [t.verdict for t in log],
            ),
        )

    def test_the_next_task_on_the_server_certifies_the_revision_at_first_use_without_the_inducer(self):
        store, log = certified_store(), TransitionLog()
        induce, calls = scripted([sticks(3), sticks(2)])
        run_episode(change_world("stick-count-2", STICKS), store, log, "hc", induce=induce)
        result = run_episode(change_world("stick-count-2", T1), store, log, "hs", induce=induce)
        revision = store.rules[f"{DEMOTED_STICK}#2"]
        first_use = next(t for t in log if t.episode == "hs" and t.target == "stick")
        self.assertEqual(
            (
                result.reason, len(calls), [t for t in log.contradictions() if t.episode == "hs"],
                first_use.test, revision.status, revision.evidence[-1], {e.split("/")[0] for e in revision.evidence},
            ),
            ("goal", 1, [], True, "certified", f"hs/{first_use.step}", {"hc", "hs"}),
        )

    def test_two_rounds_of_wrong_candidates_leave_the_rule_unknown_and_the_global_rule_planning_elsewhere(self):
        store, log = certified_store(), TransitionLog()
        induce, calls = scripted([sticks(3), sticks(5), sticks(6)], [sticks(1), sticks(7), sticks(8)])
        result = run_episode(change_world("stick-count-2", STICKS), store, log, "hc", induce=induce)
        probes = [t for t in log if t.action == "probe"]
        vanilla = plan("stick", 4, {}, store.usable("grid/vanilla"), lambda block: 1)
        self.assertEqual(
            (result.reason, len(calls), len(probes), all(p in calls[1][2] for p in probes[:3]), [s.rule_id for s in vanilla]),
            ("unrecoverable craft:stick", 2, 6, True, ["mine:log", "craft:planks", "craft:stick"]),
        )

    def test_candidates_left_untested_at_the_goal_are_tested_by_the_next_task_without_the_inducer(self):
        store, log = certified_store(), TransitionLog()
        induce, calls = scripted([sticks(3), sticks(2)])
        run_episode(change_world("stick-count-2", Task("hc", "stick")), store, log, "hc", induce=induce)
        result = run_episode(change_world("stick-count-2", STICKS), store, log, "hs", induce=induce)
        tests = [(t.rule_id, t.verdict) for t in log if t.test]
        self.assertEqual(
            (result.reason, len(calls), tests, store.rules[f"{DEMOTED_STICK}#2"].status),
            ("goal", 1, [(f"{DEMOTED_STICK}#1", "mismatch"), (f"{DEMOTED_STICK}#2", "match")], "certified"),
        )

    def test_a_candidate_no_certified_plan_can_make_the_grid_for_is_dropped_untested(self):
        log = TransitionLog()
        untestable = Rule("any", "craft", "stick", {"planks": -2, "diamond": -1, "stick": 4})
        induce, calls = scripted([untestable], [sticks(2)])
        result = run_episode(change_world("stick-count-2", STICKS), certified_store(), log, "hc", induce=induce)
        self.assertEqual(
            (result.reason, len(calls), [t.rule_id for t in log if t.action == "probe"]),
            ("goal", 2, [f"{DEMOTED_STICK}#2"]),
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

    def test_an_unknown_rule_is_routed_around_when_what_it_made_is_held(self):
        log = TransitionLog()
        induce, calls = scripted([sticks(3)], [sticks(5)])
        result = run_episode(change_world("stick-count-2", T1), certified_store(), log, "hc", induce=induce)
        self.assertEqual((result.reason, len(calls), [t.target for t in log if t.action == "craft"][-1]), ("goal", 2, "wooden_pickaxe"))

    def test_a_drop_change_is_revised_by_one_mine_test(self):
        cases = [
            ("stone-drop-nothing", T2, {}, "no certified plan"),
            ("coal_ore-drop-cobblestone", Task("hc", "torch", budget=300), {"cobblestone": 1}, "no certified plan"),
            ("log-drop-planks", Task("hc", "stick"), {"planks": 1}, "goal"),
        ]
        for change_id, task, drop, reason in cases:
            with self.subTest(change_id):
                world, log = change_world(change_id, task), TransitionLog()
                result = run_episode(world, certified_store(), log, "hc", induce=perfect(world)[0])
                tests = [(t.action, t.predicted, t.observed, t.verdict) for t in log if t.test]
                self.assertEqual((result.reason, tests), (reason, [("mine", drop, drop, "match")]))

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
                result.reason, log.contradictions(), store.rules[wrong.rule_id].status, calls[0][1].rule_id,
                {r.rule_id for r in store.rules.values() if r.status == "certified"},
            ),
            ("goal", [], "demoted", wrong.rule_id, certified),
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
    def test_c_repeats_the_failing_craft_and_d_does_not(self):
        c_log, d_log = TransitionLog(), TransitionLog()
        run_episode_c(change_world("stick-count-2", STICKS), certified_store(), c_log, "c")
        world = change_world("stick-count-2", STICKS)
        run_episode(world, certified_store(), d_log, "d", induce=perfect(world)[0])
        self.assertEqual((immediate_repeat_rate(c_log) > 0, immediate_repeat_rate(d_log)), (True, 0.0))


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
        self.assertEqual(verdicts, {change_id: (True, 0.0, True, True, 0, "goal", 0, [truth[change_id]]) for change_id in rows})


if __name__ == "__main__":
    unittest.main()
