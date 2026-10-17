from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .rules import Rule


class RuleStore:
    """Rules keyed by id, persisted as one JSON file when a path is given."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.rules: dict[str, Rule] = {}
        if path is not None and path.exists():
            for data in json.loads(path.read_text(encoding="utf-8")):
                rule = Rule.parse(data)
                self.rules[rule.rule_id] = rule

    def add(self, rule: Rule) -> None:
        self.rules[rule.rule_id] = rule
        if self.path is not None:
            payload = [r.to_dict() for r in self.rules.values()]
            self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def usable(self, server: str) -> list[Rule]:
        """Certified rules for planning on `server`. A server-scoped rule shadows the global one."""
        by_key: dict[tuple[str, str], list[Rule]] = defaultdict(list)
        for rule in self.rules.values():
            by_key[rule.key].append(rule)
        usable: list[Rule] = []
        for rules in by_key.values():
            scoped = [r for r in rules if r.scope == server]
            pool = scoped or [r for r in rules if r.scope == "global"]
            usable.extend(r for r in pool if r.status == "certified")
        return usable
