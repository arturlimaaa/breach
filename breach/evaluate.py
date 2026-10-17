"""Run a system over grid jobs into a run directory: one transition log per episode and a manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from .log import TransitionLog
from .loop import EpisodeResult, run_episode
from .store import RuleStore
from .tasks import H1, TRAINING
from .world import VANILLA, GridWorld, Ruleset, Task, rules_from_ruleset

System = Callable[[GridWorld, RuleStore, TransitionLog, str], EpisodeResult]
Job = tuple[Task, int, str, Ruleset, str | None]


def certified_vanilla() -> RuleStore:
    store = RuleStore()
    for rule in rules_from_ruleset(VANILLA, status="certified"):
        store.add(rule)
    return store


def run_jobs(
    system: System, jobs: list[Job], store_factory: Callable[[], RuleStore], out_dir: Path, carry_memory: bool = False, *, name: str
) -> Path:
    """Run each (task, seed, server, ruleset, change_id) job in order into a new `out_dir`.

    Every job gets a fresh store unless `carry_memory`, which hands the whole job list one store.
    """
    out_dir.mkdir(parents=True)
    shared = store_factory() if carry_memory else None
    episodes = []
    for task, seed, server, ruleset, change in jobs:
        episode = "-".join(part for part in (change, task.task_id, f"s{seed}") if part)
        log_path = out_dir / f"{episode}.jsonl"
        log_path.touch(exist_ok=False)  # TransitionLog appends, so a repeated job would merge two episodes
        store = shared if carry_memory else store_factory()
        world = GridWorld(task, seed, ruleset, server=server)
        result = system(world, store, TransitionLog(log_path), episode)
        # The world decides the outcome, not the system's report of it; the proof re-derives both from the log.
        episodes.append({
            "id": episode, "task": task.task_id, "server": server, "change": change, "seed": seed,
            "goal": task.goal, "count": task.count, "inventory": dict(task.inventory),
            "success": world.success, "actions": world.actions, "reason": result.reason,
        })
        # Rewritten per episode so a crash keeps the finished episodes provable.
        (out_dir / "manifest.json").write_text(json.dumps({"system": name, "episodes": episodes}, indent=2) + "\n", encoding="utf-8")
    return out_dir


def training_then_holdout(system: System, seeds: list[int], out_dir: Path, *, name: str) -> Path:
    """T1, T2, T3, then H1 on each seed, in one run directory."""
    # ponytail: every episode starts from the certified vanilla store. Once certification can change
    # the store, carry each seed's training store into its H1.
    jobs = [(task, seed, "grid/vanilla", VANILLA, None) for seed in seeds for task in (*TRAINING, H1)]
    return run_jobs(system, jobs, certified_vanilla, out_dir, name=name)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.evaluate", description="Run system D on T1, T2, T3, then H1 for each seed.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(training_then_holdout(run_episode, args.seeds, args.out_dir, name="D"))


if __name__ == "__main__":
    main()
