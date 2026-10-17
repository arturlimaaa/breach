"""Every benchmarked change on the grid, per seed and system, then the proof over the run tree."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from functools import partial
from itertools import product
from pathlib import Path

from .baseline_a import EpisodeResultA, run_episode_a, vanilla_replanner
from .baseline_b import EpisodeResultB, run_episode_b, vanilla_plan
from .changes import Change, apply, benchmark
from .evaluate import Job, certified_vanilla, run_jobs
from .llm import complete
from .log import TransitionLog
from .loop import run_episode
from .proof import proof, table
from .store import RuleStore
from .world import VANILLA, GridWorld, Task


def model(run_dir: Path, llm: bool, world: GridWorld) -> Callable[..., str]:
    """The text model for one episode: Nemotron with `llm`, else the offline vanilla replanner.

    Either way every call is logged to run_dir/model_calls.jsonl, beside the manifest the proof reads.
    """
    if llm:
        return partial(complete, env={**os.environ, "BREACH_RUN_DIR": str(run_dir)})
    return vanilla_replanner(world, {"BREACH_RUN_DIR": str(run_dir)})[0]


def run_a(run_dir: Path, llm: bool, world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResultA:
    """A plans every task from scratch, so the store goes unused."""
    return run_episode_a(world, log, episode, model(run_dir, llm, world))


def run_b(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResultB:
    """B plans from its bundled recipes, so the store goes unused."""
    return run_episode_b(world, log, episode, vanilla_plan)


def job(task_id: str, change: Change, goal: str, seed: int) -> Job:
    return (Task(task_id, goal, budget=350), seed, f"grid/{change.id}", apply(change, VANILLA), change.id)


def matrix(out_dir: Path, seeds: list[int], systems: list[str], changes: list[str] | None = None, llm: bool = False) -> dict:
    """HC for every change, seed and system; A and D then play the same world again as HS.

    D carries the store HC left behind into HS. A keeps nothing, so its HS pays for model calls again.
    """
    pairs = [(change, goal) for change, goal in benchmark() if changes is None or change.id in changes]
    out_dir.mkdir(parents=True)
    if "A" in systems:
        jobs = [job(task_id, c, goal, s) for (c, goal), s in product(pairs, seeds) for task_id in ("hc", "hs")]
        run_jobs(partial(run_a, out_dir / "A", llm), jobs, RuleStore, out_dir / "A", name="A")
    if "B" in systems:
        run_jobs(run_b, [job("hc", c, goal, s) for (c, goal), s in product(pairs, seeds)], RuleStore, out_dir / "B", name="B")
    if "D" in systems:
        # ponytail: D runs without an inducer. Once run_episode takes one, --llm hands it
        # model(<chain dir>, llm, world) the way run_a gets its planner.
        for (c, goal), s in product(pairs, seeds):
            hc_then_hs = [job("hc", c, goal, s), job("hs", c, goal, s)]
            run_jobs(run_episode, hc_then_hs, certified_vanilla, out_dir / "D" / f"{c.id}-s{s}", carry_memory=True, name="D")
    return proof(out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.matrix", description="Run every benchmarked change on the grid and print the proof table.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--systems", nargs="+", choices=("A", "B", "D"), default=["B", "D"])
    parser.add_argument("--changes", nargs="+", choices=[change.id for change, _ in benchmark()], help="only these change ids")
    parser.add_argument("--llm", action="store_true", help="A plans with Nemotron through breach.llm, not the offline vanilla replanner")
    args = parser.parse_args()
    print(table(matrix(args.out_dir, args.seeds, args.systems, args.changes, args.llm)["rows"]))


if __name__ == "__main__":
    main()
