"""A run's induction calls as NeMo Gym rollouts: each call's prompt, the model's reply, the revision the log saw pass, and a
verifiable reward, 1 when a revision of the refuted rule matched in a test or use after the call, else 0.

Each line is a nemo_gym BaseVerifyResponse, the record `gym eval run` writes to its rollouts file and the offline SFT/DPO
pipeline reads: https://docs.nvidia.com/nemo/gym/v0.7.0/tutorials/training-tutorials/offline-training-w-rollouts
Its responses_create_params also make it a NeMo Gym dataset row: https://docs.nvidia.com/nemo/gym/v0.7.0/data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .proof import _jsonl, read_log


def export(run_dir: Path) -> list[dict]:
    """One rollout per induction call of every run under `run_dir`."""
    manifests = sorted(run_dir.rglob("manifest.json"))
    if not manifests:
        raise ValueError(f"no run under {run_dir}: expected manifest.json and one <episode>.jsonl per episode")
    return [rollout for manifest in manifests for rollout in _rollouts(manifest.parent)]


def _rollouts(run: Path) -> list[dict]:
    episodes = json.loads((run / "manifest.json").read_text(encoding="utf-8"))["episodes"]
    timeline = [t for entry in episodes for t in read_log(run / f"{entry['id']}.jsonl")]
    index = {(t.episode, t.step): n for n, t in enumerate(timeline)}
    calls = [c for c in _jsonl(run / "model_calls.jsonl") if c["purpose"] == "induce"]
    at = []
    for c in calls:
        where = f"{c['episode']}/{c['step']}"
        if "messages" not in c:
            raise ValueError(f"induction call {where} has no messages: it was logged before breach.llm kept prompts")
        if (c["episode"], c["step"]) not in index:
            raise ValueError(f"induction call {where} has no transition in {run}")
        at.append(index[c["episode"], c["step"]])
    rollouts = []
    for n, (call, start) in enumerate(zip(calls, at)):
        refuted = timeline[start]
        base = refuted.rule_id.split("@")[0]
        # A call is logged at its refuting step and judged until the next call on the server; a retry or a second
        # round asks about the same step, which leaves the call before it nothing to be judged by.
        end = next((later for later in at[n + 1:] if timeline[later].server == refuted.server), len(timeline))
        # Only a reply proposes candidates, so a failed call has nothing to be judged by.
        window = timeline[start + 1:end] if "reply" in call else []
        passed = next((
            t.rule_id for t in window
            # A failed action tested nothing, though an empty prediction reads as a match.
            if t.server == refuted.server and t.ok and t.verdict == "match" and (t.rule_id or "").startswith((f"{base}@", f"{base}#"))
        ), None)
        rollouts.append(_rollout(call, f"{call['episode']}-{n}", passed))
    return rollouts


def _rollout(call: dict, response_id: str, passed: str | None) -> dict:
    output = []
    if call.get("reasoning"):
        output.append({"id": "rs_0", "type": "reasoning", "summary": [{"type": "summary_text", "text": call["reasoning"]}]})
    if "reply" in call:
        output.append({
            "id": "msg_0", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": call["reply"], "annotations": []}],
        })
    rollout = {
        "responses_create_params": {"input": call["messages"]},
        "response": {
            # model_calls.jsonl keeps no clock time.
            "id": response_id, "created_at": 0.0, "model": call["model"], "object": "response", "output": output,
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        },
        "reward": float(passed is not None),
        "candidate": passed,
        "episode": call["episode"],
        "step": call["step"],
    }
    if "error" in call:
        # The endpoint failed, not the model: mask_sample keeps the call out of NeMo Gym scores and NeMo RL losses.
        rollout |= {"mask_sample": True, "failure_reason": call["error"]}
    return rollout


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m breach.export", description="Write a run's induction calls as NeMo Gym rollouts.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("out", type=Path, help="the .jsonl file to write")
    args = parser.parse_args()
    try:
        rollouts = export(args.run_dir)
    except ValueError as err:
        raise SystemExit(f"breach.export: {err}")
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rollouts), encoding="utf-8")
    passed = sum(r["candidate"] is not None for r in rollouts)
    print(f"{len(rollouts)} induction calls, {passed} with a revision that passed, written to {args.out}")


if __name__ == "__main__":
    main()
