"""Every benchmarked change on the grid, per seed and system, then the proof over the run tree."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from functools import partial
from itertools import product
from pathlib import Path

from .baseline_a import EpisodeResultA, run_episode_a, vanilla_replanner
from .baseline_b import EpisodeResultB, run_episode_b, vanilla_plan
from .changes import Change, apply, benchmark
from .evaluate import Job, certified_vanilla, run_jobs
from .induce import induce
from .llm import complete
from .log import TransitionLog
from .loop import run_episode, run_episode_c
from .proof import proof, table
from .recover import Induce
from .reload import hr_jobs, reloading
from .store import RuleStore
from .world import VANILLA, GridWorld, Ruleset, Task, rules_from_ruleset


def nemotron(run_dir: Path) -> Callable[..., str]:
    """llm.complete with every call logged to run_dir/model_calls.jsonl, beside the manifest the proof reads."""
    return partial(complete, env={**os.environ, "BREACH_RUN_DIR": str(run_dir)})


def model(run_dir: Path, llm: bool, world: GridWorld) -> Callable[..., str]:
    """A's text model for one episode: Nemotron with `llm`, else the offline vanilla replanner, logged the same way."""
    if llm:
        return nemotron(run_dir)
    return vanilla_replanner(world, {"BREACH_RUN_DIR": str(run_dir)})[0]


def inducer_for(change: Change, run_dir: Path, llm: bool, inducer: str | None) -> Induce | None:
    """D's inducer: Nemotron with `llm`, the changed ruleset's own rule with "perfect", else none, so D stops at a contradiction."""
    if llm:
        return partial(induce, complete=nemotron(run_dir))
    if inducer == "perfect":
        return perfect(apply(change, VANILLA))
    return None


def run_a(run_dir: Path, llm: bool, world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResultA:
    """A plans every task from scratch, so the store goes unused."""
    return run_episode_a(world, log, episode, model(run_dir, llm, world))


def run_b(world: GridWorld, store: RuleStore, log: TransitionLog, episode: str) -> EpisodeResultB:
    """B plans from its bundled recipes, so the store goes unused."""
    return run_episode_b(world, log, episode, vanilla_plan)


def perfect(ruleset: Ruleset) -> Induce:
    """An inducer that knows the server: it answers with the changed ruleset's own rule for the refuted key."""
    truth = {rule.key: rule for rule in rules_from_ruleset(ruleset)}
    return lambda rule, counterexample, tail: [truth[rule.key]]


def point_latest(run_dir: Path, runs: Path) -> None:
    """Swap runs/latest over to `run_dir` in one rename, so the site and the banner follow the newest job."""
    tmp = runs / ".latest"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(run_dir.relative_to(runs))
    os.replace(tmp, runs / "latest")


def job(task_id: str, change: Change, goal: str, seed: int) -> Job:
    return (Task(task_id, goal, budget=350), seed, f"grid/{change.id}", apply(change, VANILLA), change.id)


def matrix(
    out_dir: Path, seeds: list[int], systems: list[str], changes: list[str] | None = None, llm: bool = False, inducer: str | None = None,
    sets: Sequence[str] = ("HC", "HS"),
) -> dict:
    """HC for every change, seed and system; with "HS" in `sets`, A, C and D then play the same world again.

    D carries the store HC left behind into HS. A and C start from scratch: A pays for model calls again, C meets the change again.
    With "HR", D also plays the change loaded just before its first use, then HS after it, in a chain of its own.
    """
    pairs = [(change, goal) for change, goal in benchmark() if changes is None or change.id in changes]
    after = ["hs"] if "HS" in sets else []
    hc_then_hs = [job(task_id, c, goal, s) for (c, goal), s in product(pairs, seeds) for task_id in ("hc", *after)]
    out_dir.mkdir(parents=True)
    if "HC" in sets and "A" in systems:
        run_jobs(partial(run_a, out_dir / "A", llm), hc_then_hs, RuleStore, out_dir / "A", name="A")
    if "HC" in sets and "B" in systems:
        run_jobs(run_b, [job("hc", c, goal, s) for (c, goal), s in product(pairs, seeds)], RuleStore, out_dir / "B", name="B")
    if "HC" in sets and "C" in systems:
        run_jobs(run_episode_c, hc_then_hs, certified_vanilla, out_dir / "C", name="C")
    if "D" in systems:
        for (c, goal), s in product(pairs, seeds):
            if "HC" in sets:
                d_chain(out_dir, f"{c.id}-s{s}", c, [job(task_id, c, goal, s) for task_id in ("hc", *after)], llm, inducer)
            if "HR" in sets:
                # Its HS episode has the HC chain's id, so the HR chain gets a directory of its own.
                d_chain(out_dir, f"{c.id}-s{s}-hr", c, hr_jobs(c, s)[: 1 + len(after)], llm, inducer, hr=True)
    return proof(out_dir)


def d_chain(out_dir: Path, name: str, change: Change, jobs: list[Job], llm: bool, inducer: str | None, hr: bool = False) -> None:
    """One D agent over `jobs` in out_dir/D/<name>: its store, status and model calls sit beside its manifest."""
    run_dir = out_dir / "D" / name
    system = partial(run_episode, induce=inducer_for(change, run_dir, llm, inducer), status_path=run_dir / "status.json")
    point_latest(run_dir, out_dir.parent)
    store = partial(certified_vanilla, run_dir / "store.json")
    run_jobs(reloading(system, change) if hr else system, jobs, store, run_dir, carry_memory=True, name="D")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.matrix", description="Run every benchmarked change on the grid and print the proof table.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--systems", nargs="+", choices=("A", "B", "C", "D"), default=["B", "D"])
    parser.add_argument("--changes", nargs="+", choices=[change.id for change, _ in benchmark()], help="only these change ids")
    models = parser.add_mutually_exclusive_group()
    models.add_argument("--llm", action="store_true", help="A plans and D induces with Nemotron through breach.llm")
    models.add_argument("--inducer", choices=("perfect",), help="D revises a refuted rule with the changed ruleset's own rule, offline")
    parser.add_argument("--sets", nargs="+", choices=("HC", "HR", "HS"), default=["HC", "HS"], help="HR runs for D only; HS follows each HC and HR")
    args = parser.parse_args()
    print(table(matrix(args.out_dir, args.seeds, args.systems, args.changes, args.llm, args.inducer, args.sets)["rows"]))


if __name__ == "__main__":
    main()
