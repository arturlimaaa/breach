from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .world import Observation


@dataclass(frozen=True)
class Transition:
    episode: str
    step: int
    server: str
    obs_hash: str
    action: str
    target: str | None
    rule_id: str | None
    predicted: dict[str, int]
    observed: dict[str, int]
    cls: str
    verdict: str
    test: bool = False


def obs_hash(obs: Observation) -> str:
    return hashlib.sha256(json.dumps(asdict(obs), sort_keys=True).encode()).hexdigest()[:12]


def diff(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {k: after.get(k, 0) - before.get(k, 0) for k in before.keys() | after.keys() if after.get(k, 0) != before.get(k, 0)}


def verdict(cls: str, predicted: dict[str, int], observed: dict[str, int], ok: bool) -> str:
    if cls == "exact":
        return "match" if predicted == observed else "mismatch"
    return "match" if ok else "mismatch"


class TransitionLog:
    """Append-only log, one JSON line per adapter action when a path is given."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._items: list[Transition] = []
        if path is not None and path.exists():
            self._items = [Transition(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def append(self, transition: Transition) -> None:
        self._items.append(transition)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(transition), sort_keys=True) + "\n")

    def __iter__(self) -> Iterator[Transition]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def contradictions(self) -> list[Transition]:
        return [t for t in self._items if t.cls == "exact" and t.verdict == "mismatch" and not t.test]
