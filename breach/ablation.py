"""Nemotron tier ablation on the grid: system D's matrix once per model, one row each from that run's proof.json and
model_calls.jsonl, written to <out_dir>/ablation.json and ablation.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from statistics import fmean

from .changes import benchmark
from .proof import _jsonl, _line, _num, _pct

Runner = Callable[[list[str], Mapping[str, str]], int]
HEADER = ("model", "success", "recovery mean", "recovery worst", "model calls", "tokens", "mean latency ms", "exit")


def child(argv: list[str], env: Mapping[str, str]) -> int:
    return subprocess.run(argv, env=env).returncode


def ablation(out_dir: Path, seeds: list[int], models: list[str], changes: list[str] | None = None, run: Runner = child) -> list[dict]:
    """D with the text model on the benchmarked changes, once per model into out_dir/<model>; a failed run still gets its row."""
    out_dir.mkdir(parents=True)
    rows = []
    for model in models:
        run_dir = out_dir / re.sub(r"[^\w.-]+", "-", model)
        argv = [sys.executable, "-m", "breach.matrix", str(run_dir), "--systems", "D", "--llm", "--seeds", *map(str, seeds)]
        code = run(argv + (["--changes", *changes] if changes else []), {**os.environ, "BREACH_LLM_MODEL": model})
        rows.append(row(model, run_dir, code))
        # Rewritten per model so a crash keeps the finished rows.
        (out_dir / "ablation.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        (out_dir / "ablation.md").write_text(table(rows) + "\n", encoding="utf-8")
    return rows


def row(model: str, run_dir: Path, code: int) -> dict:
    """D's aggregate from the run's proof.json, which a failed run never writes, and the cost of every logged call."""
    calls = [c for path in sorted(run_dir.rglob("model_calls.jsonl")) for c in _jsonl(path)]
    proof = run_dir / "proof.json"
    d = json.loads(proof.read_text(encoding="utf-8"))["aggregate"]["D"] if proof.exists() else {}
    return {
        "model": model, "exit": code, "success": d.get("success"),
        "recovery_latency_mean": d.get("recovery_latency_mean"), "recovery_latency_worst": d.get("recovery_latency_worst"),
        "unrecovered": d.get("unrecovered"), "model_calls": len(calls),
        "tokens": sum(c["tokens_in"] + c["tokens_out"] for c in calls),
        "latency_ms_mean": fmean(c["latency_ms"] for c in calls) if calls else None,
    }


def table(rows: list[dict]) -> str:
    lines = [_line(HEADER), _line(["---"] * len(HEADER))]
    for r in rows:
        worst = "never" if r["unrecovered"] else _num(r["recovery_latency_worst"])
        lines.append(_line([
            r["model"], _pct(r["success"]), _num(r["recovery_latency_mean"]), worst, r["model_calls"], r["tokens"],
            _num(r["latency_ms_mean"]), r["exit"],
        ]))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.ablation", description="Run system D's matrix once per text model and print one row each.")
    parser.add_argument("out_dir", type=Path, help="new run directory, e.g. runs/<name>")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--models", nargs="+", required=True, help="model ids; each run sets BREACH_LLM_MODEL to one")
    parser.add_argument("--changes", nargs="+", choices=[change.id for change, _ in benchmark()], help="only these change ids")
    args = parser.parse_args()
    print(table(ablation(args.out_dir, args.seeds, args.models, args.changes)))


if __name__ == "__main__":
    main()
