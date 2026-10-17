from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from itertools import chain
from pathlib import Path

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
    ok: bool = True
    events: list[str] = field(default_factory=list)


def obs_hash(obs: Observation) -> str:
    return hashlib.sha256(json.dumps(asdict(obs), sort_keys=True).encode()).hexdigest()[:12]


def diff(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {k: after.get(k, 0) - before.get(k, 0) for k in before.keys() | after.keys() if after.get(k, 0) != before.get(k, 0)}


def verdict(cls: str, predicted: dict[str, int], observed: dict[str, int], ok: bool, events: Sequence[str] = ()) -> str:
    """An event during the step disqualifies its evidence either way, so it is quarantined before any check."""
    if events:
        return "quarantined"
    if cls == "exact":
        return "match" if predicted == observed else "mismatch"
    if cls == "tolerant":
        return "match" if ok else "mismatch"
    return "ignored"


class TransitionLog:
    """Append-only log, one JSON line per adapter action when a path is given.

    `prior` names earlier episodes' log files of the same agent: read once, never written, and replayed before
    this log's own steps, so a certification can count evidence from another episode.
    """

    def __init__(self, path: Path | None = None, prior: Iterable[Path] = ()):
        self.path = path
        self._prior = [t for earlier in prior for t in _read(earlier)]
        self._items: list[Transition] = _read(path) if path is not None and path.exists() else []

    def append(self, transition: Transition) -> None:
        self._items.append(transition)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(transition), sort_keys=True) + "\n")

    def __iter__(self) -> Iterator[Transition]:
        return chain(self._prior, self._items)

    def __len__(self) -> int:
        return len(self._prior) + len(self._items)

    def contradictions(self) -> list[Transition]:
        return [t for t in self if t.cls == "exact" and t.verdict == "mismatch" and not t.test]


def _read(path: Path) -> list[Transition]:
    return [Transition(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]
