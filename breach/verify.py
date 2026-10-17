# Blocks whose drop is deterministic; anything else (leaves, gravel) can drop at random.
EXACT_MINES = frozenset({"log", "stone", "coal_ore"})


def classify(action: str, target: str | None, executed: bool = True, output: dict[str, object] | None = None) -> str:
    """How a step is verified: exact delta for crafts and whitelisted mines, ok-ness for moves, nothing otherwise.

    A step the world refused before acting on it says nothing about any rule, so it is judged on ok-ness alone. Nor
    does a mine whose block stayed in place: a drop rule is about what a removed block yields.
    """
    if not executed or (action == "mine" and (output or {}).get("block_removed") is False):
        return "tolerant"
    if action == "craft" or (action == "mine" and target in EXACT_MINES):
        return "exact"
    return "tolerant" if action in ("move", "place") else "ignored"
