"""Run one episode against the Mineflayer adapter into a run directory that `python3 -m breach.proof` reads."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from time import monotonic, sleep

from .changes import Change, benchmark, write_datapack
from .evaluate import certified_vanilla
from .http_world import HttpWorld
from .induce import induce
from .log import TransitionLog
from .loop import run_episode
from .matrix import nemotron, run_b
from .recover import Induce
from .reload import ReloadBeforeFirstUse, hr_task
from .store import RuleStore
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


def live(
    out_dir: Path, url: str, task: Task, system: str, pack: Pack | None = None, prior: Sequence[Path] = (), *,
    store: Path | None = None, keep_pack: bool = False, induce: Induce | None = None, change: str | None = None,
) -> Path:
    """Writes run_jobs' layout, manifest.json and <episode>.jsonl, with the task id as the episode id.

    With a `pack` (HR), the server loads it just before the first step that uses its rule and unloads it when the
    episode ends, unless `keep_pack` leaves it enabled for an HS run on the same server. `change` names the change
    an HS run's server already has, for the manifest.
    `prior` names earlier runs' logs: certification counts their evidence, and they are never copied into this log.
    D starts from `store`, an earlier run's store.json on the same server, or else from the certified vanilla rules.
    """
    world = HttpWorld(url, task)
    if pack is not None:
        world = ReloadBeforeFirstUse(world, pack.change, pack.load)
    out_dir.mkdir(parents=True)
    log = TransitionLog(out_dir / f"{task.task_id}.jsonl", prior=prior)
    if system == "D":
        # The dashboard reads both beside the manifest, as it does for a matrix job. An earlier run's store is copied, never written.
        if store is not None:
            shutil.copyfile(store, out_dir / "store.json")
        rules = RuleStore(out_dir / "store.json") if store is not None else certified_vanilla(out_dir / "store.json")
        run = partial(run_episode, induce=induce, status_path=out_dir / "status.json")
    else:
        rules, run = certified_vanilla(), SYSTEMS[system]
    try:
        result = run(world, rules, log, task.task_id)
    finally:
        if pack is not None and not keep_pack:
            pack.unload()
    # ponytail: a copy of run_jobs' entry, since run_jobs builds GridWorlds; the CLI test catches drift, and a world
    # factory on run_jobs would end the copy.
    # Like run_jobs, the outcome is the world's, not the system's claim; the proof re-derives it from the log.
    entry = {
        "id": task.task_id, "task": task.task_id, "server": world.server, "change": pack.change.id if pack else change,
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
    episode.add_argument("--hs", choices=changes, help="HS: the change's HR goal again, as task hs, on a server that already has its pack; no reload, no unload")
    parser.add_argument("--server-dir", type=Path, help="with --change: the server directory, e.g. adapter/server; its console is the screen session mc")
    parser.add_argument("--system", choices=SYSTEMS, default="D")
    parser.add_argument("--prior", nargs="+", type=Path, default=[], help="earlier runs' <episode>.jsonl logs for certification to replay")
    parser.add_argument("--store", type=Path, help="D starts from this store.json, e.g. the HR run's, for an HS run on the same server")
    parser.add_argument("--keep-pack", action="store_true", help="with --change: leave the datapack enabled for the HS run that follows")
    parser.add_argument("--llm", action="store_true", help="D induces with Nemotron through breach.llm, logging each call to the run directory")
    args = parser.parse_args()
    if args.change and args.server_dir is None:
        parser.error("--change needs --server-dir")
    pack = Pack(changes[args.change], args.server_dir) if args.change else None
    inducer = partial(induce, complete=nemotron(args.out_dir)) if args.llm else None
    if args.hs:
        task = replace(hr_task(changes[args.hs]), task_id="hs")  # as hr_jobs relabels HR's task for HS on the grid
    else:
        task = hr_task(pack.change) if pack else TASKS[args.task]
    print(live(
        args.out_dir, args.url, task, args.system, pack, args.prior,
        store=args.store, keep_pack=args.keep_pack, induce=inducer, change=args.hs,
    ))


if __name__ == "__main__":
    main()
