import random

from app.combat.formulas import ATTACK, DEFEND, DODGE, SKILL


def choose_monster_action(
    behavior_type: str, hp: int, max_hp: int, stamina: int
) -> str:
    hp_ratio = hp / max_hp if max_hp else 1.0

    weights = {
        ATTACK: 40,
        DEFEND: 20,
        DODGE: 20,
        SKILL: 20,
    }

    if behavior_type == "aggressive":
        weights[ATTACK] += 20
        weights[SKILL] += 10
    elif behavior_type == "defensive":
        weights[DEFEND] += 25
        weights[DODGE] += 10
    elif behavior_type == "trickster":
        weights[DODGE] += 25
        weights[SKILL] += 15
    elif behavior_type == "berserk":
        if hp_ratio < 0.35:
            weights[ATTACK] += 30
            weights[SKILL] += 20
    elif behavior_type == "stamina_drain":
        weights[SKILL] += 25
        weights[DEFEND] += 10

    if stamina < 20:
        weights[DEFEND] += 10
        weights[DODGE] += 10

    choices, probs = zip(*weights.items())
    return random.choices(choices, weights=probs, k=1)[0]
