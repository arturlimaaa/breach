"""Live B: rmalde/minecraft-agent's agent.mjs on our server, its model calls through a local relay, its log converted.

adapter/setup/rmalde.sh installs his code into third_party/rmalde. adapter/README.md ("Baseline B") lists the variables.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from .changes import VANILLA_IDS
from .convert_rmalde import ENDS, convert, episode, over, read_events
from .live import TASKS
from .llm import Transport, _excerpt, _headers, _provider, post
from .proof import proof, table
from .world import Task

HARNESS = Path(__file__).resolve().parents[1] / "third_party" / "rmalde"
BOT = "rmalde"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"


def relay(path: str, body: dict[str, Any], env: Mapping[str, str], transport: Transport = post) -> tuple[int, dict[str, Any]]:
    """Answer one request of models.mjs's MODEL_RELAY protocol with {data, latencyMs}, as his own relay does.

    The planner's chat completion goes to Nemotron with thinking off, in place of OpenRouter's `reasoning` field.
    A Jev decision goes to OpenRouter unchanged.
    """
    if path == "/api/v1/chat/completions":
        base, provider = _provider(env)
        off = {"reasoning_effort": "none"} if provider["thinking"] == "reasoning_effort" else {"chat_template_kwargs": {"enable_thinking": False}}
        url, headers, body = f"{base}/chat/completions", _headers(provider, env), {k: v for k, v in body.items() if k != "reasoning"} | off
    elif path == "/api/alpha/decisions":
        if not env.get("JEV_API_KEY"):
            return 502, {"error": "JEV_API_KEY is not set: Jev decisions need an OpenRouter key with access to typesafe/jev-1.13"}
        url, headers = JEV_URL, {"Content-Type": "application/json", "Authorization": f"Bearer {env['JEV_API_KEY']}"}
    else:
        return 400, {"error": f"no model behind {path}"}
    start = time.perf_counter()
    status, raw = transport(url, headers, json.dumps(body).encode())
    if status in (400, 422) and "response_format" in body:
        # NVIDIA's hosted request schema omits response_format; his planner parses the reply as JSON either way.
        body = {k: v for k, v in body.items() if k != "response_format"}
        status, raw = transport(url, headers, json.dumps(body).encode())
    if status != 200:
        return 502, {"error": f"{url} returned {_excerpt(status, raw)}"}
    return 200, {"data": json.loads(raw), "latencyMs": round((time.perf_counter() - start) * 1000)}


class Relay(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, reply = relay(request["path"], request["body"], os.environ)
        except Exception as exc:  # a missing key or an unreachable endpoint reaches his loop as a model error
            status, reply = 502, {"error": str(exc)}
        data = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        """Silent: request lines say nothing a run needs."""


def run(out_dir: Path, task: Task, seconds: float, change: str | None = None) -> Path:
    """Run agent.mjs as BOT until the episode is over, his loop ends, or `seconds` pass; then convert its log into `out_dir`."""
    if not (HARNESS / "agent.mjs").exists():
        raise SystemExit("third_party/rmalde is missing: run adapter/setup/rmalde.sh first")
    if out_dir.exists():
        raise SystemExit(f"{out_dir} exists: the run would end without a place to convert into")
    _headers(_provider(os.environ)[1], os.environ)  # a missing Nemotron key fails here, not in every plan of his
    run_dir = HARNESS / "runs" / out_dir.name
    run_dir.mkdir(parents=True)  # his agent resumes a saved status.json, so every run takes a new name
    (run_dir / "paused").touch()  # his loop idles until the start inventory is set
    feedback = run_dir / "feedback.txt"
    feedback.write_text(f"Goal for this run: hold {task.count} {task.goal}.\n", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
    Thread(target=server.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")} | {  # the keys stay with the relay
        "MODEL_RELAY": f"http://127.0.0.1:{server.server_port}",
        "PLANNER_MODEL": os.environ.get("BREACH_LLM_MODEL") or _provider(os.environ)[1]["model"],
        "MC_PORT": "25565", "BOT_NAME": BOT, "RUN_ID": run_dir.name, "FEEDBACK_FILE": str(feedback),
    }
    path = run_dir / "events.jsonl"

    def events() -> list[dict[str, Any]]:
        return read_events(path) if path.exists() else []

    def finished() -> bool:
        log = events()
        ep = episode(log, task)
        return over(ep.end, len(ep.steps), task) or any(e["type"] in ENDS for e in log)

    agent = subprocess.Popen(["node", "agent.mjs"], cwd=HARNESS, env=env)
    try:
        if not _wait(agent, lambda: any(e["type"] == "start" for e in events()), 120):
            raise RuntimeError(f"{BOT} did not join 127.0.0.1:25565: his agent exited or 120 s passed; see its output and {path}")
        for command in (f"clear {BOT}", *(f"give {BOT} {VANILLA_IDS.get(k, k)} {n}" for k, n in task.inventory.items())):
            subprocess.run(["screen", "-S", "mc", "-p", "0", "-X", "stuff", command + "\r"], check=True)
        time.sleep(2)  # the inventory packets arrive before his first observation
        (run_dir / "paused").unlink()
        _wait(agent, finished, seconds)
        (run_dir / "stop").write_text("breach.rmalde\n", encoding="utf-8")  # his loop ends at the next action boundary
        _wait(agent, lambda: any(e["type"] in ENDS for e in events()), 120)
    finally:
        agent.send_signal(signal.SIGINT)  # his handler quits the bot and exits
        try:
            agent.wait(30)
        except subprocess.TimeoutExpired:
            agent.kill()
        server.shutdown()
    return convert(path, out_dir, task, change)


def _wait(agent: subprocess.Popen, done: Callable[[], bool], seconds: float) -> bool:
    """Poll `done` each second until it holds, his process exits, or `seconds` pass."""
    deadline = time.monotonic() + seconds
    while not done():
        if agent.poll() is not None or time.monotonic() > deadline:
            return False
        time.sleep(1)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.rmalde", description="Run rmalde/minecraft-agent as B on 127.0.0.1:25565, then convert and prove its log.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>; its name is also his RUN_ID")
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--change", help="id of the change loaded on the server, recorded in the manifest")
    parser.add_argument("--seconds", type=float, default=3600, help="stop his agent after this long (default: %(default)s)")
    args = parser.parse_args()
    if not os.environ.get("JEV_API_KEY"):
        print("breach.rmalde: JEV_API_KEY is not set, so his agent plans but every Jev decision fails", file=sys.stderr)
    run(args.out_dir, TASKS[args.task], args.seconds, args.change)
    print(table(proof(args.out_dir)["rows"]))


if __name__ == "__main__":
    main()
