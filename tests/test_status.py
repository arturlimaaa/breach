import json
import tempfile
import unittest
from itertools import groupby
from pathlib import Path

from breach.log import TransitionLog
from breach.loop import Executor, run_episode
from breach.tasks import T1
from tests.test_loop import certified_store
from tests.test_recover import change_world, perfect


def statuses(writes):
    return [entry["status"] for entry in writes["plan"]]


class StatusTests(unittest.TestCase):
    def test_a_recovery_shows_the_demotion_the_revision_and_the_plan_diff(self):
        writes = []
        world = change_world("stick-count-2", T1)
        executor = Executor(world, certified_store(), TransitionLog(), "hc", induce=perfect(world)[0])
        executor.status.write = writes.append
        executor.run()
        demoted = next(w for w in writes if w["rule"] and w["rule"]["status"] == "demoted")
        replanned = next(w for w in writes[writes.index(demoted):] if "current" in statuses(w))
        revising = next(w for w in writes if w["rule"] and w["rule"]["status"] == "revising")
        focus = [status for status, _ in groupby(w["rule"]["status"] if w["rule"] else None for w in writes)]
        self.assertEqual(
            (
                focus[:5], demoted["rule"]["rule_id"], (demoted["last"]["rule_id"], demoted["last"]["verdict"]), statuses(demoted),
                statuses(replanned), revising["model"]["calls"], type(revising["model"]["last_latency_ms"]),
                [w for w in writes if statuses(w).count("current") > 1 or ("current" in statuses(w) and w["rule"] and w["rule"]["status"] in ("demoted", "revising"))],
                statuses(writes[-1]).count("current"), writes[-1]["step"],
            ),
            (
                [None, "certified", "demoted", "revising", "hypothesis"], "craft:stick@grid/stick-count-2", ("craft:stick", "mismatch"),
                ["done"] * 6 + ["aborted"] * 3, ["done"] * 6 + ["aborted"] * 3 + ["current", "pending", "pending"], 1, int,
                [], 0, world.actions,
            ),
        )

    def test_episodes_writing_one_status_path_replace_it_whole_and_keep_the_run_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            store, log = certified_store(), TransitionLog()
            hc, hs = change_world("stick-count-2", T1), change_world("stick-count-2", T1)
            induce = perfect(hc)[0]
            run_episode(hc, store, log, "hc", induce=induce, status_path=path)
            first = json.loads(path.read_text())
            run_episode(hs, store, log, "hs", induce=induce, status_path=path)
            second = json.loads(path.read_text())
            left = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(
            (
                (first["episode"], first["step"]), (second["episode"], second["step"]),
                second["started"] == first["started"], second["updated"] >= first["updated"], second["updated"][-1], left,
            ),
            (("hc", hc.actions), ("hs", hs.actions), True, True, "Z", ["status.json"]),
        )


if __name__ == "__main__":
    unittest.main()
