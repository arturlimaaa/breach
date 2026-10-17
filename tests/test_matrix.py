import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from breach.proof import read_log

ROOT = Path(__file__).resolve().parents[1]


class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.run_dir = Path(tmp.name) / "matrix"
        cls.stdout = subprocess.run(
            [sys.executable, "-m", "breach.matrix", str(cls.run_dir), "--changes", "stick-count-2", "--seeds", "1", "--systems", "B", "D"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        episodes = json.loads((cls.run_dir / "proof.json").read_text())["episodes"]
        cls.episodes = {(e["system"], e["task"]): e for e in episodes}

    def test_writes_one_manifest_per_system(self):
        self.assertEqual([m.relative_to(self.run_dir).parts[0] for m in sorted(self.run_dir.rglob("manifest.json"))], ["B", "D"])

    def test_b_contradicts_on_the_bundled_stick_recipe(self):
        log = read_log(self.run_dir / "B" / f"{self.episodes['B', 'hc']['id']}.jsonl")
        self.assertIn("bundled:craft:stick", {t.rule_id for t in log.contradictions()})

    def test_d_stops_at_the_contradiction(self):
        hc = self.episodes["D", "hc"]
        self.assertEqual((hc["change"], hc["contradictions"], hc["actions_after_contradiction"]), ("stick-count-2", 1, 0))

    def test_d_returns_to_the_server_with_the_demotion_carried(self):
        hs = self.episodes["D", "hs"]
        self.assertEqual((hs["id"], hs["contradictions"], hs["reason"]), ("stick-count-2-hs-s1", 0, "no certified plan"))

    def test_table_leads_with_a_worst_row_per_system_and_shows_hs_as_a_row(self):
        cells = [[c.strip() for c in line.split("|")[1:3]] for line in self.stdout.splitlines()[2:]]
        self.assertEqual(cells, [["B", "worst"], ["D", "worst"], ["B", "HC"], ["D", "HC"], ["D", "HS"]])


if __name__ == "__main__":
    unittest.main()
