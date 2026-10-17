# Blocks whose drop is deterministic; anything else (leaves, gravel) can drop at random.
EXACT_MINES = frozenset({"log", "stone", "coal_ore"})


def classify(action: str, target: str | None, executed: bool = True) -> str:
    """How a step is verified: exact delta for crafts and whitelisted mines, ok-ness for moves, nothing otherwise.

    A step the world refused before acting on it says nothing about any rule, so it is judged on ok-ness alone.
    """
    if not executed:
        return "tolerant"
    if action == "craft" or (action == "mine" and target in EXACT_MINES):
        return "exact"
    return "tolerant" if action in ("move", "place") else "ignored"
