import json
import tempfile
import unittest
from itertools import groupby
from pathlib import Path

from breach.log import TransitionLog
from breach.loop import run_episode
from breach.status import status_file
from breach.tasks import T1
from tests.test_loop import certified_store
from tests.test_recover import change_world, perfect


def statuses(writes):
    return [entry["status"] for entry in writes["plan"]]


class StatusTests(unittest.TestCase):
    def test_a_recovery_shows_the_demotion_the_revision_and_the_plan_diff(self):
        writes = []
        world = change_world("stick-count-2", T1)
        run_episode(world, certified_store(), TransitionLog(), "hc", induce=perfect(world)[0], status=writes.append)
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

    def test_the_status_file_is_replaced_whole_and_stamped_with_the_run_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            write = status_file(path)
            write({"step": 1})
            first = json.loads(path.read_text())
            write({"step": 2})
            second = json.loads(path.read_text())
            left = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(
            (second["step"], second["started"] == first["started"], second["updated"] >= first["updated"], second["updated"][-1], left),
            (2, True, True, "Z", ["status.json"]),
        )


if __name__ == "__main__":
    unittest.main()
