from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

ACTIONS = ("craft", "mine")
CLASSES = ("exact", "tolerant")
STATUSES = ("hypothesis", "certified", "demoted")
TOOL_TIERS = {None: 0, "wooden_pickaxe": 1, "stone_pickaxe": 2, "iron_pickaxe": 3}


@dataclass(frozen=True)
class Rule:
    """One world rule. `delta` holds consumption (negative) and production (positive)."""

    rule_id: str
    action: str
    target: str
    delta: dict[str, int]
    tool: str | None = None
    near: str | None = None
    cls: str = "exact"
    status: str = "hypothesis"
    scope: str = "global"
    source: str = "observed"
    evidence: tuple[str, ...] = ()
    revision_of: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.action, self.target)

    @property
    def inputs(self) -> dict[str, int]:
        return {item: -n for item, n in self.delta.items() if n < 0}

    @property
    def outputs(self) -> dict[str, int]:
        return {item: n for item, n in self.delta.items() if n > 0}

    @staticmethod
    def parse(data: dict[str, Any]) -> Rule:
        delta = data.get("delta")
        if not isinstance(delta, dict) or not all(
            isinstance(k, str) and isinstance(v, int) for k, v in delta.items()
        ):
            raise ValueError("delta must map item names to integers")
        rule = Rule(
            rule_id=str(data["rule_id"]),
            action=str(data["action"]),
            target=str(data["target"]),
            delta=dict(delta),
            tool=data.get("tool"),
            near=data.get("near"),
            cls=data.get("cls", "exact"),
            status=data.get("status", "hypothesis"),
            scope=str(data.get("scope", "global")),
            source=str(data.get("source", "observed")),
            evidence=tuple(str(e) for e in data.get("evidence", ())),
            revision_of=data.get("revision_of"),
        )
        for value, allowed, name in (
            (rule.action, ACTIONS, "action"),
            (rule.cls, CLASSES, "cls"),
            (rule.status, STATUSES, "status"),
            (rule.tool, TOOL_TIERS, "tool"),
        ):
            if value not in allowed:
                raise ValueError(f"{name} must be one of {tuple(allowed)}, got {value!r}")
        return rule

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data
