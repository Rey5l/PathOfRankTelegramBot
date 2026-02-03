import random
from dataclasses import dataclass


ATTACK = "ATTACK"
DEFEND = "DEFEND"
SKILL = "SKILL"
DODGE = "DODGE"
SKIP = "SKIP"

STAMINA_COSTS = {
    ATTACK: -10,
    DEFEND: -5,
    SKILL: -20,
    DODGE: -15,
    SKIP: 10,
}

MAX_STAMINA = 100
POSITIONS = ("far", "medium", "close")


@dataclass
class DamageResult:
    damage: int
    is_crit: bool
    was_miss: bool
    dodge_chance: float


def clamp_stamina(value: int) -> int:
    return max(0, min(MAX_STAMINA, value))


def base_damage(atk: int, defense: int) -> int:
    raw = int(atk - (defense * 0.5))
    return max(1, raw)


def position_damage_modifier(position: str, attacker_action: str) -> float:
    if attacker_action != ATTACK:
        return 1.0
    if position == "close":
        return 1.2
    if position == "far":
        return 0.9
    return 1.0


def position_dodge_bonus(position: str) -> float:
    if position == "close":
        return -0.10
    if position == "far":
        return 0.20
    return 0.0


def apply_stamina_penalty(damage: int, stamina: int) -> int:
    if stamina <= 0:
        return max(1, int(damage * 0.7))
    return damage


def apply_counter_rules(
    damage: int, attacker_action: str, defender_action: str
) -> DamageResult:
    if attacker_action == ATTACK and defender_action == DEFEND:
        return DamageResult(
            damage=int(damage * 0.5), is_crit=False, was_miss=False, dodge_chance=0.0
        )
    if attacker_action == ATTACK and defender_action == DODGE:
        return DamageResult(damage=0, is_crit=False, was_miss=True, dodge_chance=1.0)
    if attacker_action == SKILL and defender_action == DEFEND:
        return DamageResult(
            damage=int(damage * 1.3), is_crit=False, was_miss=False, dodge_chance=0.0
        )
    if attacker_action == SKILL and defender_action == DODGE:
        return DamageResult(damage=0, is_crit=False, was_miss=True, dodge_chance=1.0)
    return DamageResult(damage=damage, is_crit=False, was_miss=False, dodge_chance=0.0)


def apply_crit(damage: int, luck: int, position: str) -> DamageResult:
    crit_chance = luck * 0.005
    if position == "close":
        crit_chance += 0.05
    elif position == "far":
        crit_chance -= 0.03
    crit_chance = max(0.0, min(0.5, crit_chance))
    if random.random() < crit_chance:
        return DamageResult(
            damage=damage * 2, is_crit=True, was_miss=False, dodge_chance=0.0
        )
    return DamageResult(damage=damage, is_crit=False, was_miss=False, dodge_chance=0.0)


def roll_dodge(defender_luck: int, defender_action: str, position: str) -> float:
    base = 0.05 + defender_luck * 0.003
    if defender_action == DODGE:
        base += 0.25
    base += position_dodge_bonus(position)
    return max(0.0, min(0.6, base))


def compute_damage(
    atk: int,
    defense: int,
    attacker_action: str,
    defender_action: str,
    attacker_luck: int,
    attacker_stamina: int,
    defender_luck: int,
    position: str,
    skill_multiplier: float = 1.0,
) -> DamageResult:
    damage = base_damage(atk, defense)
    if attacker_action == SKILL:
        damage = int(damage * skill_multiplier)
    damage = int(damage * position_damage_modifier(position, attacker_action))
    damage = apply_stamina_penalty(damage, attacker_stamina)

    counter_result = apply_counter_rules(damage, attacker_action, defender_action)
    if counter_result.was_miss:
        return counter_result

    dodge_chance = roll_dodge(defender_luck, defender_action, position)
    if random.random() < dodge_chance:
        return DamageResult(
            damage=0, is_crit=False, was_miss=True, dodge_chance=dodge_chance
        )

    crit_result = apply_crit(counter_result.damage, attacker_luck, position)
    return DamageResult(
        damage=crit_result.damage,
        is_crit=crit_result.is_crit,
        was_miss=False,
        dodge_chance=dodge_chance,
    )
