"""Claim metrics from a run directory: per-episode numbers from the transition logs, then the results table."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import fields
from math import inf
from pathlib import Path
from statistics import fmean

from .log import Transition, TransitionLog


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line] if path.exists() else []


def read_log(path: Path) -> TransitionLog:
    """An episode's transitions, ignoring fields a system logs beyond the Transition record."""
    names = {f.name for f in fields(Transition)}
    log = TransitionLog()
    for data in _jsonl(path):
        log.append(Transition(**{k: v for k, v in data.items() if k in names}))
    return log


def measure(entry: dict, system: str, log: TransitionLog, calls: list[dict], later: list[Transition]) -> dict:
    """The manifest entry, once the log confirms its action count and success, plus the first contradiction's metrics and the text-model cost.

    `later` holds the transitions of the run's later episodes on the same server, where a recovery may first show.
    """
    if len(log) != entry["actions"]:
        raise ValueError(f"episode {entry['id']}: {len(log)} logged transitions for {entry['actions']} actions; the log must have one line per action")
    held = Counter(entry["inventory"])
    for t in log:
        # A probe observes the output slot and takes its ingredients back, so it never changes the inventory.
        if t.action != "probe":
            held.update(t.observed)
    if (held[entry["goal"]] >= entry["count"]) != entry["success"]:
        raise ValueError(
            f"episode {entry['id']}: the log ends holding {held[entry['goal']]} of {entry['count']} {entry['goal']},"
            f" but the manifest says success is {entry['success']}"
        )
    hits = log.contradictions()
    record = {
        **entry, "system": system, "contradictions": len(hits), "actions_after_contradiction": None,
        "immediate_repeat": None, "recovery_latency": None, "text_model_calls": len(calls),
        "tokens": sum(c["tokens_in"] + c["tokens_out"] for c in calls),
    }
    if not hits:
        return record
    first = hits[0]
    steps = list(log)
    rest = steps[steps.index(first) + 1:]

    def same(t: Transition) -> bool:
        return (t.action, t.target) == (first.action, first.target)

    def revises(t: Transition) -> bool:
        # The server copy is <rule_id>@<server> and each candidate <rule_id>#n, at any depth.
        return t.rule_id is not None and t.rule_id.startswith((f"{first.rule_id}@", f"{first.rule_id}#"))

    # Reaching the same block again takes looks and moves, so the repeat is judged on the next step that is neither,
    # and not a test: a recovery test re-runs the step under a candidate's revised prediction.
    after = [t for t in rest if t.action not in ("move", "look")]
    attempt = next((t for t in after if not t.test), None)
    return record | {
        "actions_after_contradiction": sum(t.rule_id == first.rule_id for t in after),
        "immediate_repeat": int(attempt is not None and same(attempt)),
        "recovery_latency": next((n for n, t in enumerate([*rest, *later], 1) if revises(t) and t.verdict == "match"), None),
    }


def summarize(system: str, label: str, episodes: list[dict], worst: bool = False) -> dict:
    """One table row: means over `episodes`, or each column's worst episode when `worst`. Recovery always gives both."""
    pick = max if worst else fmean
    hit = [e for e in episodes if e["contradictions"]]
    wins = [e["actions"] for e in episodes if e["success"]]
    recovered = [e["recovery_latency"] for e in hit if e["recovery_latency"] is not None]
    return {
        "system": system,
        "set": label,
        "episodes": len(episodes),
        "success": (min if worst else fmean)([float(e["success"]) for e in episodes]),
        "actions_per_success": pick(wins) if wins else None,
        "contradicted": len(hit),
        "actions_after_contradiction": pick([e["actions_after_contradiction"] for e in hit]) if hit else None,
        "immediate_repeat": pick([e["immediate_repeat"] for e in hit]) if hit else None,
        "recovery_latency_mean": fmean(recovered) if recovered else None,
        "recovery_latency_worst": max(recovered, default=None),
        "unrecovered": len(hit) - len(recovered),
        "text_model_calls": pick([e["text_model_calls"] for e in episodes]),
        "tokens": pick([e["tokens"] for e in episodes]),
    }


def rows(episodes: list[dict]) -> list[dict]:
    """The worst-case row of each system first, then one row per system and task set."""
    systems = sorted({e["system"] for e in episodes})
    groups = sorted(dict.fromkeys((e["system"], e["task"].upper()) for e in episodes), key=lambda key: key[0])
    return [summarize(s, "worst", [e for e in episodes if e["system"] == s], worst=True) for s in systems] + [
        summarize(s, label, [e for e in episodes if (e["system"], e["task"].upper()) == (s, label)]) for s, label in groups
    ]


def worst_case(episodes: list[dict]) -> dict:
    """The slowest recovery; one that never happened ranks worst. The episode is None when nothing contradicted."""
    hit = [e for e in episodes if e["contradictions"]]
    if not hit:
        return {"episode": None, "recovery_latency": None}
    worst = max(hit, key=lambda e: inf if e["recovery_latency"] is None else e["recovery_latency"])
    return {"episode": worst["id"], "recovery_latency": worst["recovery_latency"]}


def read_run(run_dir: Path) -> list[dict]:
    """Measured episodes of the one system whose manifest.json sits in `run_dir`, in the order they ran."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    calls = _jsonl(run_dir / "model_calls.jsonl")
    entries = manifest["episodes"]
    logs = [read_log(run_dir / f"{entry['id']}.jsonl") for entry in entries]
    measured = []
    for i, (entry, log) in enumerate(zip(entries, logs)):
        # ponytail: later episodes on the server count as the same agent's, true of every run here that revises;
        # record carry_memory in the manifest before a run that revises without it revisits a server.
        later = [t for e, other in zip(entries[i + 1:], logs[i + 1:]) if e["server"] == entry["server"] for t in other]
        measured.append(measure(entry, manifest["system"], log, [c for c in calls if c["episode"] == entry["id"]], later))
    return measured


def proof(run_dir: Path) -> dict:
    """Metrics of every run under `run_dir`, one manifest per system and run."""
    manifests = sorted(run_dir.rglob("manifest.json"))
    if not manifests:
        raise ValueError(f"no run under {run_dir}: expected manifest.json and one <episode>.jsonl per episode")
    episodes = [e for manifest in manifests for e in read_run(manifest.parent)]
    systems = {s: [e for e in episodes if e["system"] == s] for s in sorted({e["system"] for e in episodes})}
    result = {
        "episodes": episodes,
        "rows": rows(episodes),
        # Keyed by system for the site: the slowest recovery, and the mean row over every episode.
        "worst_case": {s: worst_case(own) for s, own in systems.items()},
        "aggregate": {s: summarize(s, "all", own) for s, own in systems.items()},
    }
    (run_dir / "proof.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


HEADER = (
    "system", "set", "episodes", "success", "actions/success", "contradicted", "after contradiction",
    "immediate repeat", "recovery mean", "recovery worst", "model calls/episode", "tokens/episode",
)


def _num(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f}".removesuffix(".0")


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def _line(cells) -> str:
    return "| " + " | ".join(map(str, cells)) + " |"


def table(rows: list[dict]) -> str:
    lines = [_line(HEADER), _line(["---"] * len(HEADER))]
    for r in rows:
        worst = "never" if r["unrecovered"] else _num(r["recovery_latency_worst"])
        lines.append(_line([
            r["system"], r["set"], r["episodes"], _pct(r["success"]), _num(r["actions_per_success"]), r["contradicted"],
            _num(r["actions_after_contradiction"]), _pct(r["immediate_repeat"]), _num(r["recovery_latency_mean"]), worst,
            _num(r["text_model_calls"]), _num(r["tokens"]),
        ]))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.proof", description="Write proof.json for a run directory and print the results table.")
    parser.add_argument("run_dir", type=Path)
    run_dir = parser.parse_args().run_dir
    try:
        result = proof(run_dir)
    except ValueError as err:
        raise SystemExit(f"breach.proof: {err}")
    print(table(result["rows"]))


if __name__ == "__main__":
    main()
