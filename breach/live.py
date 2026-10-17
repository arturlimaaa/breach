"""Run one episode against the Mineflayer adapter into a run directory that `python3 -m breach.proof` reads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluate import certified_vanilla
from .http_world import HttpWorld
from .log import TransitionLog
from .loop import run_episode
from .matrix import run_b
from .tasks import H1, H2, T1, T2, T3
from .world import Task

TASKS = {task.task_id.upper(): task for task in (T1, T2, T3, H1, H2)}
SYSTEMS = {"D": run_episode, "B": run_b}


def live(out_dir: Path, url: str, task: Task, system: str) -> Path:
    """Writes run_jobs' layout, manifest.json and <episode>.jsonl, with the task id as the episode id."""
    world = HttpWorld(url, task)
    out_dir.mkdir(parents=True)
    log = TransitionLog(out_dir / f"{task.task_id}.jsonl")
    result = SYSTEMS[system](world, certified_vanilla(), log, task.task_id)
    # ponytail: run_jobs' manifest entry, copied because run_jobs builds GridWorlds; give it a world factory if live runs grow jobs.
    entry = {
        "id": task.task_id, "task": task.task_id, "server": world.server, "change": None, "seed": None,
        "reset": world.reset_message, "success": result.success, "actions": result.actions, "reason": result.reason,
    }
    (out_dir / "manifest.json").write_text(json.dumps({"system": system, "episodes": [entry]}, indent=2) + "\n", encoding="utf-8")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.live", description="Run one episode against the adapter.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--url", default="http://127.0.0.1:3100", help="adapter base URL (default: %(default)s, the adapter's PORT)")
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--system", choices=SYSTEMS, default="D")
    args = parser.parse_args()
    print(live(args.out_dir, args.url, TASKS[args.task], args.system))


if __name__ == "__main__":
    main()
