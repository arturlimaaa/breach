# Blocks whose drop is deterministic; anything else (leaves, gravel) can drop at random.
EXACT_MINES = frozenset({"log", "stone", "coal_ore"})


def classify(action: str, target: str | None, ok: bool = True) -> str:
    """How a step is verified: exact delta for crafts and whitelisted mines, ok-ness for moves, nothing otherwise.

    A mine that left its block in place failed to act, so its empty delta says nothing about the drop.
    """
    if action == "mine" and not ok:
        return "tolerant"
    if action == "craft" or (action == "mine" and target in EXACT_MINES):
        return "exact"
    return "tolerant" if action in ("move", "place") else "ignored"
