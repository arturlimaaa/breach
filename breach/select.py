from __future__ import annotations

from .rules import Rule


def order_tests(candidates: list[Rule], inventory: dict[str, int]) -> list[Rule]:
    """Cheapest discriminating test first.

    A probe of held inputs costs 1 and each missing input unit adds 1. Ties go to the grid
    that differs from more of the other candidates' grids, then to the rule id.
    """

    def key(candidate: Rule) -> tuple[int, int, str]:
        missing = sum(max(0, n - inventory.get(item, 0)) for item, n in candidate.inputs.items())
        differs = sum(other.inputs != candidate.inputs for other in candidates)
        return (1 + missing, -differs, candidate.rule_id)

    return sorted(candidates, key=key)
