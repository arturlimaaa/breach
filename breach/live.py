"""Run one episode against the Mineflayer adapter into a run directory that `python3 -m breach.proof` reads."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from .changes import Change, benchmark, write_datapack
from .evaluate import certified_vanilla
from .http_world import HttpWorld
from .log import TransitionLog
from .loop import run_episode
from .matrix import run_b
from .reload import ReloadBeforeFirstUse, hr_task
from .tasks import H1, H2, T1, T2, T3
from .world import Task

TASKS = {task.task_id.upper(): task for task in (T1, T2, T3, H1, H2)}
SYSTEMS = {"D": run_episode, "B": run_b}
SCREEN = ("screen", "-S", "mc", "-p", "0", "-X", "stuff")  # types into the console of the server's screen session


@dataclass(frozen=True)
class Pack:
    """`change` as a datapack of the server in `server_dir`, switched on and off through its console."""

    change: Change
    server_dir: Path
    run: Callable[..., object] = subprocess.run
    timeout: float = 60

    def load(self) -> None:
        write_datapack(self.change, self.server_dir / "world" / "datapacks" / self.change.id)
        # A reload enables a new pack unless the world lists it as disabled, which is how `unload` leaves it.
        self.console(["reload", f'datapack enable "file/{self.change.id}"'], enabled=True)

    def unload(self) -> None:
        self.console([f'datapack disable "file/{self.change.id}"'], enabled=False)

    def console(self, commands: list[str], enabled: bool) -> None:
        """Type `commands`, then wait for the listing of enabled packs and raise unless it shows the pack `enabled` or not.

        A reload logs "Reloading!" before it runs and holds the console until it is done, so only a line typed after it shows its outcome.
        """
        log = self.server_dir / "logs" / "latest.log"
        start = log.stat().st_size
        for command in [*commands, "datapack list enabled"]:
            self.run([*SCREEN, command + "\r"], check=True)
        deadline = monotonic() + self.timeout
        while (listing := _listing(log, start)) is None:
            if monotonic() >= deadline:
                raise TimeoutError(f"{log} shows no data pack listing within {self.timeout} s of {commands}")
            sleep(0.2)
        if bool(re.search(rf"file/{re.escape(self.change.id)}(?![\w-])", listing)) != enabled:
            raise RuntimeError(f"after {commands} the server lists: {listing.strip()}")


def _listing(log: Path, start: int) -> str | None:
    """The first whole reply to `datapack list enabled` in `log` after byte `start`."""
    with log.open("rb") as fh:
        fh.seek(start)
        lines = fh.read().decode(errors="replace").splitlines(keepends=True)
    return next((line for line in lines if line.endswith("\n") and "data packs enabled" in line), None)


def live(out_dir: Path, url: str, task: Task, system: str, pack: Pack | None = None) -> Path:
    """Writes run_jobs' layout, manifest.json and <episode>.jsonl, with the task id as the episode id.

    With a `pack` (HR), the server loads it just before the first step that uses its rule and unloads it when the episode ends.
    """
    world = HttpWorld(url, task)
    if pack is not None:
        world = ReloadBeforeFirstUse(world, pack.change, pack.load)
    out_dir.mkdir(parents=True)
    log = TransitionLog(out_dir / f"{task.task_id}.jsonl")
    try:
        result = SYSTEMS[system](world, certified_vanilla(), log, task.task_id)
    finally:
        if pack is not None:
            pack.unload()
    # ponytail: a copy of run_jobs' entry, since run_jobs builds GridWorlds; the CLI test catches drift, and a world
    # factory on run_jobs would end the copy.
    # Like run_jobs, the outcome is the world's, not the system's claim; the proof re-derives it from the log.
    entry = {
        "id": task.task_id, "task": task.task_id, "server": world.server, "change": None if pack is None else pack.change.id,
        "seed": None, "goal": task.goal, "count": task.count, "inventory": dict(task.inventory),
        "success": world.success, "actions": world.actions, "reason": result.reason, "reset": world.reset_message,
    }
    if pack is not None:
        entry["reload_step"] = world.reload_step
    (out_dir / "manifest.json").write_text(json.dumps({"system": system, "episodes": [entry]}, indent=2) + "\n", encoding="utf-8")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.live", description="Run one episode against the adapter.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--url", default="http://127.0.0.1:3100", help="adapter base URL (default: %(default)s, the adapter's PORT)")
    changes = {change.id: change for change, _ in benchmark()}
    episode = parser.add_mutually_exclusive_group(required=True)
    episode.add_argument("--task", choices=TASKS)
    episode.add_argument("--change", choices=changes, help="HR: the change's goal from a vanilla start, its datapack loaded just before the first use of its rule")
    parser.add_argument("--server-dir", type=Path, help="with --change: the server directory, e.g. adapter/server; its console is the screen session mc")
    parser.add_argument("--system", choices=SYSTEMS, default="D")
    args = parser.parse_args()
    if args.change and args.server_dir is None:
        parser.error("--change needs --server-dir")
    pack = Pack(changes[args.change], args.server_dir) if args.change else None
    print(live(args.out_dir, args.url, hr_task(pack.change) if pack else TASKS[args.task], args.system, pack))


if __name__ == "__main__":
    main()
