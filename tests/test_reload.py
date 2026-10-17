import json
import tempfile
import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path

from breach.changes import apply, enumerate_class
from breach.evaluate import run_jobs
from breach.live import Pack, live
from breach.log import TransitionLog
from breach.loop import run_episode
from breach.proof import proof, read_log
from breach.reload import ReloadBeforeFirstUse, hr_jobs, hr_task, reloading
from breach.tasks import T1
from breach.world import VANILLA, GridWorld, Task, rules_from_ruleset
from tests.fake_adapter import serve
from tests.test_loop import certified_store
from tests.test_recover import recording, true_delta

CHANGES = {change.id: change for change in enumerate_class()}
STICK_COUNT = CHANGES["stick-count-2"]
HR_CHANGES = ("stick-count-2", "stick-swap-planks-log", "log-drop-planks")  # a count, a swap, and a drop on a mine
LADDER = Task("hr", "ladder", budget=350)  # seven sticks, so two stick crafts under vanilla
SCREEN = ["screen", "-S", "mc", "-p", "0", "-X", "stuff"]


def knowing(change):
    """Perfect inducer for the server `change` is loaded on: the changed ruleset's own rule for the refuted key."""
    truth = {rule.key: rule for rule in rules_from_ruleset(apply(change, VANILLA))}
    return recording(lambda rule: [truth[rule.key]])


def hr_then_hs(change, seed=1):
    """hr_jobs through run_jobs and the proof, as the matrix would run them.

    Returns the proof's HR and HS episodes, the HR log, the episode each inducer call came from, and the store they shared.
    """
    store, (induce, calls) = certified_store(), knowing(change)
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "D"
        run_jobs(reloading(partial(run_episode, induce=induce), change), hr_jobs(change, seed), lambda: store, run, carry_memory=True, name="D")
        hr, hs = proof(run)["episodes"]
        return hr, hs, read_log(run / f"{hr['id']}.jsonl"), [counterexample.episode for _, counterexample, _ in calls], store


class SecondStick(GridWorld):
    """Vanilla until stick-count-2 loads just before its second stick craft, so the first one matched on this server."""

    crafts = 0

    def step(self, action):
        if (action.name, action.target) == ("craft", "stick"):
            self.crafts += 1
            if self.crafts == 2:
                self.ruleset = apply(STICK_COUNT, VANILLA)
        return super().step(action)


def console(server_dir, change, worlds, enables=True):
    """A `run` for Pack that plays the 1.16.5 console behind screen for one pack, and the argv it was called with.

    The pack is on while `worlds[-1]`, the adapter's world, has the change's rules; it goes on only once its pack.mcmeta is
    on disk. `datapack list enabled` appends the listing to logs/latest.log.
    """
    typed, log, pack = [], server_dir / "logs" / "latest.log", f"file/{change.id}"
    log.parent.mkdir(parents=True)
    log.write_text('[15:00:00] [Server thread/INFO]: Done (8.1s)! For help, type "help"\n')

    def run(argv, check):
        typed.append(argv)
        command = argv[-1].removesuffix("\r")
        if command in ("reload", f'datapack enable "{pack}"') and enables and (server_dir / "world" / "datapacks" / change.id / "pack.mcmeta").exists():
            worlds[-1].ruleset = apply(change, VANILLA)
        if command == f'datapack disable "{pack}"':
            worlds[-1].ruleset = VANILLA
        if command == "datapack list enabled":
            packs = ["[vanilla (built-in)]"] + [f"[{pack} (world)]"] * (worlds[-1].ruleset != VANILLA)
            with log.open("a") as fh:
                fh.write(f"[15:00:01] [Server thread/INFO]: There are {len(packs)} data packs enabled: {', '.join(packs)}\n")

    return run, typed


class ReloadTests(unittest.TestCase):
    def test_the_load_runs_once_just_before_the_first_step_that_uses_the_rule_and_changes_nothing_else(self):
        plain, wrapped_log, loads = TransitionLog(), TransitionLog(), []
        run_episode(GridWorld(LADDER, 1), certified_store(), plain, "hr")
        world = GridWorld(LADDER, 1)
        wrapped = ReloadBeforeFirstUse(world, STICK_COUNT, lambda: loads.append(world.actions))
        run_episode(wrapped, certified_store(), wrapped_log, "hr")
        first_use = next(t.step for t in plain if t.target == "stick")
        self.assertEqual((loads, wrapped.reload_step, list(wrapped_log)), ([first_use - 1], first_use, list(plain)))

    def test_hr_through_run_jobs_contradicts_at_the_first_use_recovers_with_no_reuse_and_its_hs_calls_no_inducer(self):
        for change_id in HR_CHANGES:
            with self.subTest(change_id):
                change = CHANGES[change_id]
                hr, hs, hr_log, called_from, store = hr_then_hs(change)
                first = hr_log.contradictions()[0]
                first_use = next(t.step for t in hr_log if t.rule_id == first.rule_id)
                self.assertEqual(
                    (
                        [ruleset for _, _, _, ruleset, _ in hr_jobs(change, 1)], first.step, hr["success"], hr["actions_after_contradiction"],
                        called_from, hs["contradictions"], hs["success"], store.rules[f"{first.rule_id}@{first.server}"].delta,
                    ),
                    ([VANILLA, apply(change, VANILLA)], first_use, True, 0, [hr["id"]], 0, True, true_delta(change)),
                )

    def test_hs_certifies_the_revision_by_replaying_an_hr_log_where_no_step_used_the_rule_before_the_reload(self):
        for change_id in HR_CHANGES:
            with self.subTest(change_id):
                change = CHANGES[change_id]
                store, log, (induce, _) = certified_store(), TransitionLog(), knowing(change)
                system = reloading(partial(run_episode, induce=induce), change)
                # One log for both episodes: certification replays the server's history, which run_jobs splits per episode.
                for task, seed, server, ruleset, _ in hr_jobs(change, 1):
                    system(GridWorld(task, seed, ruleset, server=server), store, log, task.task_id)
                first = log.contradictions()[0]
                record = store.rules[f"{first.rule_id}@{first.server}"]
                self.assertEqual(
                    (record.status, record.delta, sorted({e.split("/")[0] for e in record.evidence})),
                    ("certified", true_delta(change), ["hr", "hs"]),
                )

    def test_a_rule_used_before_the_reload_never_certifies_its_revision_there_yet_plans_as_test_steps_without_the_inducer(self):
        store, log, (induce, calls) = certified_store(), TransitionLog(), knowing(STICK_COUNT)
        server = f"grid/{STICK_COUNT.id}"
        hr = run_episode(SecondStick(LADDER, 1, server=server), store, log, "hr", induce=induce)
        hs = run_episode(GridWorld(replace(LADDER, task_id="hs"), 1, apply(STICK_COUNT, VANILLA), server=server), store, log, "hs", induce=induce)
        sticks = [(t.episode, t.test, t.verdict) for t in log if (t.action, t.target) == ("craft", "stick")]
        self.assertEqual(
            (hr.reason, hs.reason, [c.episode for _, c, _ in calls], store.rules[f"craft:stick@{server}"].status, sticks),
            (
                "goal", "goal", ["hr"], "hypothesis",
                [("hr", False, "match"), ("hr", False, "mismatch"), ("hr", True, "match"), *[("hs", True, "match")] * 4],
            ),
        )


class LiveReloadTests(unittest.TestCase):
    def test_an_hr_run_over_the_adapter_loads_the_pack_just_before_its_first_use_and_unloads_it_at_the_end(self):
        worlds = []

        def make(task):
            worlds.append(GridWorld(task, seed=1))
            return worlds[-1]

        httpd = serve(make)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            server_dir, run_dir = Path(tmp) / "server", Path(tmp) / "run"
            run, typed = console(server_dir, STICK_COUNT, worlds)
            live(run_dir, f"http://127.0.0.1:{httpd.server_address[1]}", hr_task(STICK_COUNT), "D", Pack(STICK_COUNT, server_dir, run))
            [entry] = json.loads((run_dir / "manifest.json").read_text())["episodes"]
            [proven] = proof(run_dir)["episodes"]
            first = read_log(run_dir / "hr.jsonl").contradictions()[0]
        self.assertEqual(
            (typed, entry["change"], entry["reload_step"], first.rule_id, proven["actions_after_contradiction"], worlds[-1].ruleset),
            (
                [
                    [*SCREEN, "reload\r"], [*SCREEN, 'datapack enable "file/stick-count-2"\r'], [*SCREEN, "datapack list enabled\r"],
                    [*SCREEN, 'datapack disable "file/stick-count-2"\r'], [*SCREEN, "datapack list enabled\r"],
                ],
                "stick-count-2", first.step, "craft:stick", 0, VANILLA,
            ),
        )

    def test_a_pack_the_server_does_not_list_after_the_reload_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = console(Path(tmp), STICK_COUNT, [GridWorld(T1, 1)], enables=False)
            with self.assertRaisesRegex(RuntimeError, r"There are 1 data packs enabled: \[vanilla \(built-in\)\]"):
                Pack(STICK_COUNT, Path(tmp), run).load()

    def test_a_server_that_never_lists_its_packs_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = console(Path(tmp), STICK_COUNT, [GridWorld(T1, 1)])
            with self.assertRaises(TimeoutError):
                Pack(STICK_COUNT, Path(tmp), lambda argv, check: None, timeout=0).load()


if __name__ == "__main__":
    unittest.main()
