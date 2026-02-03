from __future__ import annotations


RANK_LETTERS = ["F", "D", "C", "B", "A", "S"]
SUBRANKS_PER_LETTER = 3


def xp_to_next_level(level: int) -> int:
    base = 100
    linear = 40 * (level - 1)
    curve = 10 * (level - 1) * (level - 1)
    return base + linear + curve


def rank_from_level(level: int) -> str:
    step = min((level - 1) // 5, (len(RANK_LETTERS) * SUBRANKS_PER_LETTER) - 1)
    letter = RANK_LETTERS[step // SUBRANKS_PER_LETTER]
    plus_count = step % SUBRANKS_PER_LETTER
    return f"{letter}{'+' * plus_count}"


def apply_leveling(level: int, xp: int) -> tuple[int, int, int]:
    new_level = max(1, level)
    new_xp = max(0, xp)
    levels_gained = 0
    while new_xp >= xp_to_next_level(new_level):
        new_xp -= xp_to_next_level(new_level)
        new_level += 1
        levels_gained += 1
    return new_level, new_xp, levels_gained


def level_stat_growth(levels_gained: int) -> dict[str, int]:
    if levels_gained <= 0:
        return {"hp": 0, "stamina": 0, "attack": 0, "defense": 0, "luck": 0}
    return {
        "hp": 10 * levels_gained,
        "stamina": 5 * levels_gained,
        "attack": 2 * levels_gained,
        "defense": 2 * levels_gained,
        "luck": 1 * levels_gained,
    }
