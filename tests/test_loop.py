import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from breach.certify import replay
from breach.log import TransitionLog
from breach.loop import run_episode
from breach.store import RuleStore
from breach.tasks import H1, H2, T1, T2
from breach.world import VANILLA, GridWorld, Recipe, Task, rules_from_ruleset

GOLDEN = Path(__file__).parent / "golden"


def certified_store():
    store = RuleStore()
    for rule in rules_from_ruleset(VANILLA, status="certified"):
        store.add(rule)
    return store


def stick_count(n):
    return replace(VANILLA, recipes={**VANILLA.recipes, "stick": Recipe({"planks": 2}, n, None)})


class Hurt(GridWorld):
    """Fires a damage event on every stick craft."""

    def step(self, action):
        result = super().step(action)
        return replace(result, events=["damage"]) if action.target == "stick" else result


class Slippery(GridWorld):
    """Its first mine is refused before the world is touched, as the adapter's is when no path reaches the block."""

    missed = False

    def _mine(self, action):
        if self.missed:
            return super()._mine(action)
        self.missed = True
        return self._result(False, "no path to the log", executed=False)


class Tableless(GridWorld):
    """Its first 3x3 craft is refused before the world is touched, as live run 3's was: no crafting table within reach."""

    refused = False

    def _craft(self, action):
        recipe = self.ruleset.recipes.get(action.target or "")
        if self.refused or recipe is None or recipe.station is None:
            return super()._craft(action)
        self.refused = True
        return self._result(False, "no crafting table within 16 blocks", executed=False)


class LoopTests(unittest.TestCase):
    def test_empty_store_issues_zero_crafts(self):
        log = TransitionLog()
        result = run_episode(GridWorld(T1, seed=1), RuleStore(), log, "t1")
        self.assertEqual((result.success, [t for t in log if t.action == "craft"]), (False, []))

    def test_prior_store_reaches_a_wooden_pickaxe_within_budget(self):
        log = TransitionLog()
        result = run_episode(GridWorld(T1, seed=1), certified_store(), log, "t1")
        mined = {(t.target, t.cls) for t in log if t.action == "mine"}
        self.assertEqual(
            (result.success, len(log) == result.actions, log.contradictions(), mined),
            (True, True, [], {("log", "exact")}),
        )

    def test_glance_reaches_a_wooden_pickaxe_on_h2_within_budget(self):
        outcomes = []
        for seed in range(1, 6):
            log = TransitionLog()
            result = run_episode(GridWorld(H2, seed=seed), certified_store(), log, "h2")
            outcomes.append((seed, result.success, len(log) == result.actions))
        self.assertEqual(outcomes, [(seed, True, True) for seed in range(1, 6)])

    def test_logs_in_sight_need_no_glance(self):
        log = TransitionLog()
        result = run_episode(GridWorld(T1, seed=1), certified_store(), log, "t1")
        self.assertEqual(
            (result.actions, [(t.action, t.target) for t in log if t.action != "move"]),
            (20, [("mine", "log"), ("craft", "planks"), ("craft", "crafting_table"), ("mine", "log"), ("craft", "planks"),
                  ("craft", "stick"), ("mine", "log"), ("craft", "planks"), ("place", "crafting_table"), ("craft", "wooden_pickaxe")]),
        )

    def test_a_table_is_placed_once_before_the_first_3x3_craft_and_walked_back_to_for_the_next(self):
        log = TransitionLog()
        result = run_episode(GridWorld(T2, seed=1), certified_store(), log, "t2")
        stations = [(t.action, t.target) for t in log if t.action == "place" or t.target in ("wooden_pickaxe", "stone_pickaxe")]
        self.assertEqual(
            (result.reason, stations, log.contradictions()),
            ("goal", [("place", "crafting_table"), ("craft", "wooden_pickaxe"), ("craft", "stone_pickaxe")], []),
        )

    def test_a_refused_mine_is_a_failed_step_and_a_changed_drop_still_contradicts(self):
        log = TransitionLog()
        result = run_episode(Slippery(Task("p", "planks"), seed=1), certified_store(), log, "p")
        nothing = replace(VANILLA, drops={**VANILLA.drops, "stone": {}})
        dropped = run_episode(GridWorld(T2, seed=1, ruleset=nothing, server="grid/stone-drop-nothing"), certified_store(), TransitionLog(), "hc")
        self.assertEqual(
            (result.reason, [(t.cls, t.verdict) for t in log if t.action == "mine"], log.contradictions(), dropped.reason),
            ("goal", [("tolerant", "mismatch"), ("exact", "match")], [], "contradiction at mine:stone"),
        )

    def test_a_craft_refused_without_a_station_is_a_failed_step_and_a_refused_recipe_still_contradicts(self):
        log, changed_log = TransitionLog(), TransitionLog()
        result = run_episode(Tableless(T1, seed=1), certified_store(), log, "t1")
        coal = replace(VANILLA, recipes={**VANILLA.recipes, "stone_pickaxe": Recipe({"cobblestone": 3, "stick": 2, "coal": 1}, 1)})
        changed = run_episode(GridWorld(T2, seed=1, ruleset=coal, server="grid/stone-pickaxe-add-coal"), certified_store(), changed_log, "hc")
        self.assertEqual(
            (
                result.reason, [(t.cls, t.verdict) for t in log if t.target == "wooden_pickaxe"], log.contradictions(),
                changed.reason, [(t.target, t.cls) for t in changed_log.contradictions()],
            ),
            ("goal", [("tolerant", "mismatch"), ("exact", "match")], [], "contradiction at craft:stone_pickaxe", [("stone_pickaxe", "exact")]),
        )

    def test_t1_seed_1_logs_the_golden_transitions(self):
        log = TransitionLog()
        run_episode(GridWorld(T1, seed=1), certified_store(), log, "t1")
        self.assertEqual(list(log), list(TransitionLog(GOLDEN / "d-t1-s1.jsonl")))

    def test_partial_inventory_skips_the_crafting_table(self):
        log = TransitionLog()
        result = run_episode(GridWorld(H1, seed=2), certified_store(), log, "h1")
        self.assertEqual(
            (result.success, [t.target for t in log if t.action == "craft"]),
            (True, ["stick", "planks", "wooden_pickaxe", "stone_pickaxe"]),
        )

    def test_budget_exhausted_on_arrival_logs_no_phantom_step(self):
        log = TransitionLog()
        result = run_episode(GridWorld(replace(T1, budget=8), seed=1), certified_store(), log, "t1")
        self.assertEqual((len(log), log.contradictions(), result.reason), (result.actions, [], "budget"))

    def test_count_change_aborts_at_the_craft_step(self):
        world = GridWorld(T1, seed=1, ruleset=stick_count(2), server="grid/stick-count-2")
        log = TransitionLog()
        result = run_episode(world, certified_store(), log, "hc")
        contradiction = log.contradictions()[0]
        after = [t for t in log if t.step > contradiction.step]
        self.assertEqual(
            (result.success, contradiction.target, contradiction.observed, after),
            (False, "stick", {"planks": -2, "stick": 2}, []),
        )

    def test_a_server_demotion_leaves_vanilla_planning_on_the_global_rule(self):
        store, log = certified_store(), TransitionLog()
        run_episode(GridWorld(T1, seed=1, ruleset=stick_count(2), server="grid/stick-count-2"), store, log, "hc")
        result = run_episode(GridWorld(T1, seed=1), store, log, "t1")
        stick = store.rules["craft:stick"]
        demoted = replace(stick, rule_id="craft:stick@grid/stick-count-2", scope="grid/stick-count-2", status="demoted", revision_of="craft:stick")
        self.assertEqual(
            (result.success, stick.status, store.rules.get(demoted.rule_id)),
            (True, "certified", demoted),
        )

    def test_quarantined_mismatch_replans_instead_of_contradicting(self):
        world = Hurt(T1, seed=1, ruleset=stick_count(1), server="grid/stick-count-1")
        log = TransitionLog()
        result = run_episode(world, certified_store(), log, "hq")
        self.assertEqual(
            (result.success, log.contradictions(), {t.verdict for t in log if t.target == "stick"}),
            (True, [], {"quarantined"}),
        )

    def test_replaying_a_saved_log_reproduces_every_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            log = TransitionLog(path)
            run_episode(Hurt(T1, seed=1, ruleset=stick_count(1), server="grid/stick-count-1"), certified_store(), log, "hq")
            run_episode(GridWorld(T1, seed=1, ruleset=stick_count(2), server="grid/stick-count-2"), certified_store(), log, "hc")
            saved = TransitionLog(path)
        self.assertEqual(
            ({t.verdict for t in saved}, replay(saved)),
            ({"match", "mismatch", "quarantined"}, [t.verdict for t in log]),
        )


if __name__ == "__main__":
    unittest.main()
