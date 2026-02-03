from dataclasses import dataclass
import random

from app.combat.ai import choose_monster_action
from app.combat.formulas import (
    ATTACK,
    DEFEND,
    DODGE,
    SKILL,
    SKIP,
    STAMINA_COSTS,
    MAX_STAMINA,
    DamageResult,
    POSITIONS,
    clamp_stamina,
    compute_damage,
)
from app.ui import templates


@dataclass
class FighterState:
    name: str
    hp: int
    stamina: int
    atk: int
    defense: int
    luck: int
    max_hp: int


def apply_stamina(action: str, stamina: int, override_cost: int | None = None) -> int:
    if override_cost is not None:
        delta = -abs(override_cost)
    else:
        delta = STAMINA_COSTS.get(action, 0)
    return clamp_stamina(stamina + delta)


def _roll_damage_log(actor: str, result: DamageResult) -> str:
    if result.was_miss:
        return f"🏃 {actor} промахивается."
    if result.is_crit:
        return f"💥 {actor} наносит критический удар на {result.damage}."
    return f"⚔️ {actor} наносит {result.damage} урона."


def _shift_position(current: str, player_action: str, enemy_action: str) -> str:
    idx = POSITIONS.index(current)
    delta = 0
    if player_action == ATTACK:
        delta -= 1
    elif player_action == DODGE:
        delta += 1
    if enemy_action == ATTACK:
        delta -= 1
    elif enemy_action == DODGE:
        delta += 1
    new_idx = max(0, min(len(POSITIONS) - 1, idx + delta))
    return POSITIONS[new_idx]


def process_pve_turn(
    player_action: str,
    player: FighterState,
    monster: FighterState,
    monster_behavior: str,
    battle_turn: int,
    position: str,
    player_bonus: dict,
    monster_bonus: dict,
    player_status_text: str,
    monster_status_text: str,
    combo_text: str,
    player_skill_cost: int | None,
    monster_skill_cost: int | None,
    player_skill_multiplier: float,
    monster_skill_multiplier: float,
) -> tuple[str, str, int, int, int, int, bool, bool, str]:
    monster_action = choose_monster_action(
        monster_behavior, monster.hp, monster.max_hp, monster.stamina
    )

    player.stamina = apply_stamina(player_action, player.stamina, player_skill_cost)
    monster.stamina = apply_stamina(monster_action, monster.stamina, monster_skill_cost)

    player_damage = compute_damage(
        atk=player.atk,
        defense=monster.defense,
        attacker_action=player_action,
        defender_action=monster_action,
        attacker_luck=player.luck,
        attacker_stamina=player.stamina,
        defender_luck=monster.luck,
        position=position,
        ignore_def_pct=player_bonus.get("ignore_def_pct", 0.0),
        bonus_damage_pct=player_bonus.get("damage_pct", 0.0),
        bonus_crit_pct=player_bonus.get("crit_pct", 0.0),
        bonus_dodge_pct=monster_bonus.get("dodge_pct", 0.0),
        skill_multiplier=player_skill_multiplier if player_action == SKILL else 1.0,
    )
    monster_damage = compute_damage(
        atk=monster.atk,
        defense=player.defense,
        attacker_action=monster_action,
        defender_action=player_action,
        attacker_luck=monster.luck,
        attacker_stamina=monster.stamina,
        defender_luck=player.luck,
        position=position,
        ignore_def_pct=monster_bonus.get("ignore_def_pct", 0.0),
        bonus_damage_pct=monster_bonus.get("damage_pct", 0.0),
        bonus_crit_pct=monster_bonus.get("crit_pct", 0.0),
        bonus_dodge_pct=player_bonus.get("dodge_pct", 0.0),
        skill_multiplier=monster_skill_multiplier if monster_action == SKILL else 1.0,
    )

    monster.hp = max(0, monster.hp - player_damage.damage)
    player.hp = max(0, player.hp - monster_damage.damage)

    new_position = _shift_position(position, player_action, monster_action)
    log_lines = [
        templates.round_header(battle_turn),
        templates.round_separator(),
        f"🧍 Дистанция: {templates.distance_visual(position)}",
        f"⚡ STA: Игрок {player.stamina} | Монстр {monster.stamina}",
        f"🧪 Эффекты: Игрок {player_status_text} | Монстр {monster_status_text}",
        combo_text,
        f"🧝 Игрок -> {templates.action_label(player_action)} | 👹 Монстр -> {templates.action_label(monster_action)}",
        f"📍 Позиция: {templates.position_label(position)} → {templates.position_label(new_position)}",
        _roll_damage_log("Игрок", player_damage),
        _roll_damage_log(monster.name, monster_damage),
        f"❤️ HP Игрока: {player.hp} | 💀 HP Монстра: {monster.hp}",
        templates.round_separator(),
    ]

    return (
        monster_action,
        "\n".join(log_lines),
        player.hp,
        player.stamina,
        monster.hp,
        monster.stamina,
        player.hp <= 0,
        monster.hp <= 0,
        new_position,
    )


def process_pvp_turn(
    player_action: str,
    enemy_action: str,
    player: FighterState,
    enemy: FighterState,
    battle_turn: int,
    position: str,
    player_bonus: dict,
    enemy_bonus: dict,
    player_status_text: str,
    enemy_status_text: str,
    combo_text: str,
    player_skill_cost: int | None,
    enemy_skill_cost: int | None,
    player_skill_multiplier: float,
    enemy_skill_multiplier: float,
) -> tuple[str, str, int, int, int, int, bool, bool, str]:
    player.stamina = apply_stamina(player_action, player.stamina, player_skill_cost)
    enemy.stamina = apply_stamina(enemy_action, enemy.stamina, enemy_skill_cost)

    player_damage = compute_damage(
        atk=player.atk,
        defense=enemy.defense,
        attacker_action=player_action,
        defender_action=enemy_action,
        attacker_luck=player.luck,
        attacker_stamina=player.stamina,
        defender_luck=enemy.luck,
        position=position,
        ignore_def_pct=player_bonus.get("ignore_def_pct", 0.0),
        bonus_damage_pct=player_bonus.get("damage_pct", 0.0),
        bonus_crit_pct=player_bonus.get("crit_pct", 0.0),
        bonus_dodge_pct=enemy_bonus.get("dodge_pct", 0.0),
        skill_multiplier=player_skill_multiplier if player_action == SKILL else 1.0,
    )
    enemy_damage = compute_damage(
        atk=enemy.atk,
        defense=player.defense,
        attacker_action=enemy_action,
        defender_action=player_action,
        attacker_luck=enemy.luck,
        attacker_stamina=enemy.stamina,
        defender_luck=player.luck,
        position=position,
        ignore_def_pct=enemy_bonus.get("ignore_def_pct", 0.0),
        bonus_damage_pct=enemy_bonus.get("damage_pct", 0.0),
        bonus_crit_pct=enemy_bonus.get("crit_pct", 0.0),
        bonus_dodge_pct=player_bonus.get("dodge_pct", 0.0),
        skill_multiplier=enemy_skill_multiplier if enemy_action == SKILL else 1.0,
    )

    # ±10% randomness for PVP balance
    player_damage.damage = int(player_damage.damage * random.uniform(0.9, 1.1))
    enemy_damage.damage = int(enemy_damage.damage * random.uniform(0.9, 1.1))

    enemy.hp = max(0, enemy.hp - player_damage.damage)
    player.hp = max(0, player.hp - enemy_damage.damage)

    new_position = _shift_position(position, player_action, enemy_action)
    log_lines = [
        templates.round_header(battle_turn),
        templates.round_separator(),
        f"🧍 Дистанция: {templates.distance_visual(position)}",
        f"⚡ STA: Игрок {player.stamina} | Противник {enemy.stamina}",
        f"🧪 Эффекты: Игрок {player_status_text} | Противник {enemy_status_text}",
        combo_text,
        f"🧝 Игрок -> {templates.action_label(player_action)} | 🧟 Противник -> {templates.action_label(enemy_action)}",
        f"📍 Позиция: {templates.position_label(position)} → {templates.position_label(new_position)}",
        _roll_damage_log("Игрок", player_damage),
        _roll_damage_log("Противник", enemy_damage),
        f"❤️ HP Игрока: {player.hp} | 💀 HP Противника: {enemy.hp}",
        templates.round_separator(),
    ]

    return (
        enemy_action,
        "\n".join(log_lines),
        player.hp,
        player.stamina,
        enemy.hp,
        enemy.stamina,
        player.hp <= 0,
        enemy.hp <= 0,
        new_position,
    )
