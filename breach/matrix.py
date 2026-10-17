"""Every benchmarked change on the grid, per seed and system, then the proof over the run tree."""

from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

from .baseline_b import EpisodeResultB, run_episode_b, vanilla_plan
from .changes import Change, apply, benchmark
from .evaluate import Job, certified_vanilla, run_jobs
from .log import TransitionLog
from .loop import run_episode
from .proof import proof, table
from .store import RuleStore
from .world import VANILLA, GridWorld, Task


def run_b(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResultB:
    """B plans from its bundled recipes, so the store goes unused."""
    return run_episode_b(world, log, episode, vanilla_plan)


def job(task_id: str, change: Change, goal: str, seed: int) -> Job:
    return (Task(task_id, goal, budget=350), seed, f"grid/{change.id}", apply(change, VANILLA), change.id)


def matrix(out_dir: Path, seeds: list[int], systems: list[str], changes: list[str] | None = None) -> dict:
    """HC for every change, seed and system. D then returns to each HC server with the store HC left behind (HS)."""
    pairs = [(change, goal) for change, goal in benchmark() if changes is None or change.id in changes]
    out_dir.mkdir(parents=True)
    if "B" in systems:
        run_jobs(run_b, [job("hc", c, goal, s) for (c, goal), s in product(pairs, seeds)], RuleStore, out_dir / "B", name="B")
    if "D" in systems:
        for (c, goal), s in product(pairs, seeds):
            hc_then_hs = [job("hc", c, goal, s), job("hs", c, goal, s)]
            run_jobs(run_episode, hc_then_hs, certified_vanilla, out_dir / "D" / f"{c.id}-s{s}", carry_memory=True, name="D")
    return proof(out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.matrix", description="Run every benchmarked change on the grid and print the proof table.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--systems", nargs="+", choices=("B", "D"), default=["B", "D"])
    parser.add_argument("--changes", nargs="+", choices=[change.id for change, _ in benchmark()], help="only these change ids")
    args = parser.parse_args()
    print(table(matrix(args.out_dir, args.seeds, args.systems, args.changes)["rows"]))


if __name__ == "__main__":
    main()
