from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

from app import state
import json
from app.combat.engine import FighterState, process_pve_turn, process_pvp_turn
from app.combat.formulas import ATTACK, DEFEND, DODGE, SKILL, SKIP, POSITIONS, clamp_stamina
from app.combat.status import apply_dot_effects, effects_to_modifiers, parse_effects_json, summarize_effects
from app.combat.combo import apply_combo, dump_combo_state, load_combo_state
from app.db import (
    add_battle_message,
    delete_battle_message,
    get_battle,
    get_connection,
    get_monster_by_id,
    get_player_by_id,
    get_player_by_telegram,
    get_skill_by_id,
    get_player_skill_meta,
    list_battle_messages,
    list_battle_effects,
    list_player_skills,
    reward_player,
    increment_wins,
    tick_battle_effects,
    upsert_battle_effect,
    update_battle,
    update_player_battle,
)
from app.keyboards import battle_keyboard, skills_select_keyboard
from app.ui import templates
from app.cases import roll_quest_case_drop
from app.db import grant_case


router = Router()
KEEP_BATTLE_MESSAGES = 2


def _range_allows(position: str, skill_range: str) -> bool:
    if skill_range == "MELEE":
        return position == "close"
    if skill_range == "MID":
        return position in {"close", "medium"}
    if skill_range == "LONG":
        return position in {"medium", "far"}
    return True


def _build_bonus_from_effects(effects_rows: list) -> dict:
    parsed = [
        {
            "effect_type": row["effect_type"],
            "value": row["value"],
            "duration": row["duration"],
            "stacks": row["stacks"],
        }
        for row in effects_rows
    ]
    return effects_to_modifiers(parsed)


def _shift_position_by_delta(position: str, delta: int) -> str:
    idx = POSITIONS.index(position)
    new_idx = max(0, min(len(POSITIONS) - 1, idx + delta))
    return POSITIONS[new_idx]


def _apply_skill_effects(
    conn,
    battle_id: int,
    target: str,
    effects_json: str,
) -> dict:
    effects = parse_effects_json(effects_json)
    immediate = {"stamina_restore": 0, "move": 0, "ignore_def": 0, "damage_up": 0}
    for eff in effects:
        etype = eff.get("type")
        value = eff.get("value", 0)
        duration = eff.get("duration", 1)
        max_stacks = eff.get("max_stacks", 1)
        eff_target = eff.get("target", target)
        if etype in {"stamina_restore", "move", "ignore_def", "damage_up"}:
            immediate[etype] += value
            continue
        upsert_battle_effect(
            conn,
            battle_id=battle_id,
            target=eff_target,
            effect_type=etype,
            value=value,
            duration=duration,
            max_stacks=max_stacks,
        )
    return immediate


async def _send_battle_message(
    source: Message,
    conn,
    battle_id: int,
    text: str,
    reply_markup=None,
) -> None:
    sent = await source.answer(text, reply_markup=reply_markup)
    add_battle_message(conn, battle_id, sent.chat.id, sent.message_id)
    await _cleanup_battle_messages(source, conn, battle_id, sent.chat.id)


async def _cleanup_battle_messages(
    source: Message, conn, battle_id: int, chat_id: int
) -> None:
    rows = list_battle_messages(conn, battle_id, chat_id)
    for row in rows[KEEP_BATTLE_MESSAGES:]:
        try:
            await source.bot.delete_message(chat_id=chat_id, message_id=row["message_id"])
        except TelegramBadRequest:
            pass
        delete_battle_message(conn, row["id"])


@router.message(Command("battle"))
async def cmd_battle(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player or not player.current_battle_id:
        await message.answer("🗺 Активных боев нет. Возьми контракт через /quest.")
        conn.close()
        return

    battle = get_battle(conn, player.current_battle_id)
    if not battle or battle.status != "active":
        update_player_battle(conn, player.id, None)
        await message.answer("🏁 Бой завершен или не найден.")
        conn.close()
        return

    await _send_battle_message(
        message,
        conn,
        battle.id,
        f"⚔️ Ход {battle.turn}. Выбери действие:",
        reply_markup=battle_keyboard(),
    )
    conn.close()


@router.callback_query(lambda c: c.data and c.data.startswith("battle:"))
async def callback_battle_action(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    if action not in {ATTACK, DEFEND, SKILL, DODGE, SKIP}:
        await callback.answer("Неизвестное действие.")
        return

    if not state.db_path:
        await callback.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, callback.from_user.id)
    if not player or not player.current_battle_id:
        await callback.answer("Нет активного боя.")
        conn.close()
        return

    battle = get_battle(conn, player.current_battle_id)
    if not battle or battle.status != "active":
        update_player_battle(conn, player.id, None)
        await callback.answer("Бой завершен.")
        conn.close()
        return

    if action == SKILL:
        skills = list_player_skills(conn, player.id)
        available = [
            skill
            for skill in skills
            if _range_allows(battle.position, skill.range)
            and skill.stamina_cost <= battle.player_stamina
        ]
        if not available:
            await callback.answer("Нет доступных навыков по позиции.")
            conn.close()
            return
        await _send_battle_message(
            callback.message,
            conn,
            battle.id,
            "💥 Выбери навык:",
            reply_markup=skills_select_keyboard(available),
        )
        await callback.answer()
        conn.close()
        return

    if battle.type == "PVE":
        monster = get_monster_by_id(conn, battle.monster_id)
        player_effects_rows = list_battle_effects(conn, battle.id, "player")
        monster_effects_rows = list_battle_effects(conn, battle.id, "enemy")
        battle.player_hp, player_dot = apply_dot_effects(player_effects_rows, battle.player_hp)
        battle.enemy_hp, monster_dot = apply_dot_effects(monster_effects_rows, battle.enemy_hp)
        player_bonus = _build_bonus_from_effects(player_effects_rows)
        monster_bonus = _build_bonus_from_effects(monster_effects_rows)
        if player_bonus.get("stunned"):
            action = SKIP

        player_combo_state = load_combo_state(battle.player_combo_json)
        player_combo_state, combo_result = apply_combo(player_combo_state, [], action)
        battle.player_combo_json = dump_combo_state(player_combo_state)
        combo_text = (
            f"🔗 Комбо: шагов {player_combo_state['steps']} | осталось {player_combo_state['remaining']}"
            if player_combo_state["active"]
            else "🔗 Комбо: нет"
        )

        player_def = int(player.defense * (1 + player_bonus.get("def_pct", 0.0) / 100))
        monster_def = int(monster.defense * (1 + monster_bonus.get("def_pct", 0.0) / 100))
        player_state = FighterState(
            name=player.username,
            hp=battle.player_hp,
            stamina=battle.player_stamina,
            atk=player.attack,
            defense=player_def,
            luck=player.luck,
            max_hp=player.hp,
        )
        monster_state = FighterState(
            name=monster.name,
            hp=battle.enemy_hp,
            stamina=battle.enemy_stamina,
            atk=monster.atk,
            defense=monster_def,
            luck=4,
            max_hp=monster.hp,
        )

        (
            monster_action,
            log_entry,
            player_hp,
            player_sta,
            monster_hp,
            monster_sta,
            player_dead,
            monster_dead,
            new_position,
        ) = process_pve_turn(
            player_action=action,
            player=player_state,
            monster=monster_state,
            monster_behavior=monster.behavior_type,
            battle_turn=battle.turn,
            position=battle.position,
            player_bonus=player_bonus,
            monster_bonus=monster_bonus,
            player_status_text=summarize_effects(player_effects_rows),
            monster_status_text=summarize_effects(monster_effects_rows),
            combo_text=combo_text,
            player_skill_cost=None,
            monster_skill_cost=None,
            player_skill_multiplier=1.0,
            monster_skill_multiplier=1.0,
        )

        battle.turn += 1
        battle.player_action = action
        battle.enemy_action = monster_action
        battle.player_hp = player_hp
        battle.player_stamina = player_sta
        battle.enemy_hp = monster_hp
        battle.enemy_stamina = monster_sta
        battle.position = new_position
        battle.log = templates.trim_battle_log(
            (battle.log + "\n\n" + log_entry).strip()
        )
        tick_battle_effects(conn, battle.id)

        if player_dead:
            battle.status = "lose"
            update_player_battle(conn, player.id, None)
            result_text = "💀 Ты проиграл. Часть золота потеряна."
            reward_player(conn, player.id, xp=0, gold=-10)
        elif monster_dead:
            battle.status = "win"
            update_player_battle(conn, player.id, None)
            reward_player(
                conn, player.id, xp=monster.reward_xp, gold=monster.reward_gold
            )
            increment_wins(conn, player.id, 1)
            drop_case = roll_quest_case_drop(player.rank)
            drop_text = ""
            if drop_case:
                grant_case(conn, player.id, drop_case, 1)
                drop_text = f"\n🎁 Выпал кейс: {drop_case}"
            result_text = (
                f"🏆 Победа! +{monster.reward_xp} XP, +{monster.reward_gold} золота."
                f"{drop_text}"
            )
        else:
            result_text = "⚔️ Бой продолжается."
    else:
        p1 = get_player_by_id(conn, battle.player_id)
        p2 = get_player_by_id(conn, battle.enemy_player_id)
        if not p1 or not p2:
            update_player_battle(conn, player.id, None)
            await callback.answer("Противник не найден.")
            conn.close()
            return

        if player.id == battle.player_id:
            battle.player_action = action
            battle.player_skill_id = None
            side_label = "Игрок"
        else:
            battle.enemy_action = action
            battle.enemy_skill_id = None
            side_label = "Противник"

        if not battle.player_action or not battle.enemy_action:
            update_battle(conn, battle)
            await _send_battle_message(
                callback.message,
                conn,
                battle.id,
                f"⏳ {side_label} выбрал действие. Ожидаем второго игрока.",
            )
            await callback.answer()
            conn.close()
            return

        player_effects_rows = list_battle_effects(conn, battle.id, "player")
        enemy_effects_rows = list_battle_effects(conn, battle.id, "enemy")
        battle.player_hp, _ = apply_dot_effects(player_effects_rows, battle.player_hp)
        battle.enemy_hp, _ = apply_dot_effects(enemy_effects_rows, battle.enemy_hp)
        player_bonus = _build_bonus_from_effects(player_effects_rows)
        enemy_bonus = _build_bonus_from_effects(enemy_effects_rows)

        if player_bonus.get("stunned"):
            battle.player_action = SKIP
        if enemy_bonus.get("stunned"):
            battle.enemy_action = SKIP

        player_combo_state = load_combo_state(battle.player_combo_json)
        enemy_combo_state = load_combo_state(battle.enemy_combo_json)
        player_combo_state, _ = apply_combo(player_combo_state, [], battle.player_action)
        enemy_combo_state, _ = apply_combo(enemy_combo_state, [], battle.enemy_action)
        battle.player_combo_json = dump_combo_state(player_combo_state)
        battle.enemy_combo_json = dump_combo_state(enemy_combo_state)
        combo_text = (
            f"🔗 Комбо: Игрок {player_combo_state['steps']}/{player_combo_state['remaining']} | "
            f"Противник {enemy_combo_state['steps']}/{enemy_combo_state['remaining']}"
        )

        p1_def = int(p1.defense * (1 + player_bonus.get("def_pct", 0.0) / 100))
        p2_def = int(p2.defense * (1 + enemy_bonus.get("def_pct", 0.0) / 100))
        player_state = FighterState(
            name=p1.username,
            hp=battle.player_hp,
            stamina=battle.player_stamina,
            atk=p1.attack,
            defense=p1_def,
            luck=p1.luck,
            max_hp=p1.hp,
        )
        enemy_state = FighterState(
            name=p2.username,
            hp=battle.enemy_hp,
            stamina=battle.enemy_stamina,
            atk=p2.attack,
            defense=p2_def,
            luck=p2.luck,
            max_hp=p2.hp,
        )

        (
            _enemy_action,
            log_entry,
            player_hp,
            player_sta,
            enemy_hp,
            enemy_sta,
            player_dead,
            enemy_dead,
            new_position,
        ) = process_pvp_turn(
            player_action=battle.player_action,
            enemy_action=battle.enemy_action,
            player=player_state,
            enemy=enemy_state,
            battle_turn=battle.turn,
            position=battle.position,
            player_bonus=player_bonus,
            enemy_bonus=enemy_bonus,
            player_status_text=summarize_effects(player_effects_rows),
            enemy_status_text=summarize_effects(enemy_effects_rows),
            combo_text=combo_text,
            player_skill_cost=None,
            enemy_skill_cost=None,
            player_skill_multiplier=1.0,
            enemy_skill_multiplier=1.0,
        )

        battle.turn += 1
        battle.player_action = None
        battle.enemy_action = None
        battle.player_hp = player_hp
        battle.player_stamina = player_sta
        battle.enemy_hp = enemy_hp
        battle.enemy_stamina = enemy_sta
        battle.position = new_position
        battle.log = templates.trim_battle_log(
            (battle.log + "\n\n" + log_entry).strip()
        )
        tick_battle_effects(conn, battle.id)

        if player_dead or enemy_dead:
            battle.status = "win"
            update_player_battle(conn, battle.player_id, None)
            update_player_battle(conn, battle.enemy_player_id, None)
            result_text = "🏁 Дуэль завершена."
        else:
            result_text = "⚔️ Дуэль продолжается."

    update_battle(conn, battle)
    await _send_battle_message(
        callback.message,
        conn,
        battle.id,
        f"{log_entry}\n\n{result_text}",
    )
    if battle.status == "active":
        await _send_battle_message(
            callback.message,
            conn,
            battle.id,
            "🎯 Выбери действие:",
            reply_markup=battle_keyboard(),
        )
    await callback.answer()
    conn.close()


@router.callback_query(lambda c: c.data and c.data.startswith("skill:"))
async def callback_skill_action(callback: CallbackQuery) -> None:
    if not state.db_path:
        await callback.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, callback.from_user.id)
    if not player or not player.current_battle_id:
        await callback.answer("Нет активного боя.")
        conn.close()
        return

    battle = get_battle(conn, player.current_battle_id)
    if not battle or battle.status != "active":
        await callback.answer("Бой завершен.")
        conn.close()
        return

    skill_id = int(callback.data.split(":")[1])
    skill = get_skill_by_id(conn, skill_id)
    if not skill or not _range_allows(battle.position, skill.range):
        await callback.answer("Навык недоступен на этой дистанции.")
        conn.close()
        return

    if battle.type == "PVE":
        monster = get_monster_by_id(conn, battle.monster_id)
        player_effects_rows = list_battle_effects(conn, battle.id, "player")
        monster_effects_rows = list_battle_effects(conn, battle.id, "enemy")
        battle.player_hp, _ = apply_dot_effects(player_effects_rows, battle.player_hp)
        battle.enemy_hp, _ = apply_dot_effects(monster_effects_rows, battle.enemy_hp)

        player_bonus = _build_bonus_from_effects(player_effects_rows)
        monster_bonus = _build_bonus_from_effects(monster_effects_rows)
        if player_bonus.get("stunned"):
            await callback.answer("Ты оглушен.")
            conn.close()
            return

        immediate = _apply_skill_effects(conn, battle.id, "enemy", skill.effects_json)
        player_bonus["ignore_def_pct"] = immediate["ignore_def"]
        player_bonus["damage_pct"] = player_bonus.get("damage_pct", 0.0) + immediate["damage_up"]
        battle.player_stamina = clamp_stamina(battle.player_stamina + immediate["stamina_restore"])
        meta = get_player_skill_meta(conn, player.id, skill.id)
        skill_level = meta["level"] if meta else 1
        skill_multiplier = skill.damage_multiplier * (1 + 0.05 * (skill_level - 1))

        tags = json.loads(skill.combo_tags_json) if skill.combo_tags_json else []
        combo_state = load_combo_state(battle.player_combo_json)
        combo_state, combo_result = apply_combo(combo_state, tags, SKILL)
        battle.player_combo_json = dump_combo_state(combo_state)
        if combo_result.get("finisher_effect"):
            fin = combo_result["finisher_effect"]
            upsert_battle_effect(
                conn,
                battle.id,
                "enemy",
                fin["type"],
                fin["value"],
                fin["duration"],
                fin["max_stacks"],
            )
        player_bonus["damage_pct"] = player_bonus.get("damage_pct", 0.0) + combo_result.get(
            "bonus_damage_pct", 0
        )
        combo_text = (
            f"🔗 Комбо: шагов {combo_state['steps']} | осталось {combo_state['remaining']}"
            if combo_state["active"]
            else "🔗 Комбо: нет"
        )

        player_def = int(player.defense * (1 + player_bonus.get("def_pct", 0.0) / 100))
        monster_def = int(monster.defense * (1 + monster_bonus.get("def_pct", 0.0) / 100))
        player_state = FighterState(
            name=player.username,
            hp=battle.player_hp,
            stamina=battle.player_stamina,
            atk=player.attack,
            defense=player_def,
            luck=player.luck,
            max_hp=player.hp,
        )
        monster_state = FighterState(
            name=monster.name,
            hp=battle.enemy_hp,
            stamina=battle.enemy_stamina,
            atk=monster.atk,
            defense=monster_def,
            luck=4,
            max_hp=monster.hp,
        )

        (
            monster_action,
            log_entry,
            player_hp,
            player_sta,
            monster_hp,
            monster_sta,
            player_dead,
            monster_dead,
            new_position,
        ) = process_pve_turn(
            player_action=SKILL,
            player=player_state,
            monster=monster_state,
            monster_behavior=monster.behavior_type,
            battle_turn=battle.turn,
            position=battle.position,
            player_bonus=player_bonus,
            monster_bonus=monster_bonus,
            player_status_text=summarize_effects(player_effects_rows),
            monster_status_text=summarize_effects(monster_effects_rows),
            combo_text=combo_text,
            player_skill_cost=skill.stamina_cost,
            monster_skill_cost=None,
            player_skill_multiplier=skill_multiplier,
            monster_skill_multiplier=1.0,
        )

        if immediate["move"]:
            new_position = _shift_position_by_delta(new_position, int(immediate["move"]))

        battle.turn += 1
        battle.player_action = SKILL
        battle.enemy_action = monster_action
        battle.player_hp = player_hp
        battle.player_stamina = player_sta
        battle.enemy_hp = monster_hp
        battle.enemy_stamina = monster_sta
        battle.position = new_position
        battle.log = templates.trim_battle_log((battle.log + "\n\n" + log_entry).strip())

        if player_dead:
            battle.status = "lose"
            update_player_battle(conn, player.id, None)
            result_text = "💀 Ты проиграл. Часть золота потеряна."
            reward_player(conn, player.id, xp=0, gold=-10)
        elif monster_dead:
            battle.status = "win"
            update_player_battle(conn, player.id, None)
            reward_player(conn, player.id, xp=monster.reward_xp, gold=monster.reward_gold)
            increment_wins(conn, player.id, 1)
            drop_case = roll_quest_case_drop(player.rank)
            drop_text = ""
            if drop_case:
                grant_case(conn, player.id, drop_case, 1)
                drop_text = f"\n🎁 Выпал кейс: {drop_case}"
            result_text = f"🏆 Победа! +{monster.reward_xp} XP, +{monster.reward_gold} золота.{drop_text}"
        else:
            result_text = "⚔️ Бой продолжается."

        tick_battle_effects(conn, battle.id)
        update_battle(conn, battle)
        await _send_battle_message(
            callback.message,
            conn,
            battle.id,
            f"{log_entry}\n\n{result_text}",
        )
        if battle.status == "active":
            await _send_battle_message(
                callback.message,
                conn,
                battle.id,
                "🎯 Выбери действие:",
                reply_markup=battle_keyboard(),
            )
        await callback.answer()
        conn.close()
        return

    if player.id == battle.player_id:
        battle.player_action = SKILL
        battle.player_skill_id = skill.id
        side_label = "Игрок"
    else:
        battle.enemy_action = SKILL
        battle.enemy_skill_id = skill.id
        side_label = "Противник"

    if not battle.player_action or not battle.enemy_action:
        update_battle(conn, battle)
        await _send_battle_message(
            callback.message,
            conn,
            battle.id,
            f"⏳ {side_label} выбрал навык. Ожидаем второго игрока.",
        )
        await callback.answer()
        conn.close()
        return

    p1 = get_player_by_id(conn, battle.player_id)
    p2 = get_player_by_id(conn, battle.enemy_player_id)
    if not p1 or not p2:
        update_player_battle(conn, player.id, None)
        await callback.answer("Противник не найден.")
        conn.close()
        return

    skill_p1 = get_skill_by_id(conn, battle.player_skill_id) if battle.player_skill_id else None
    skill_p2 = get_skill_by_id(conn, battle.enemy_skill_id) if battle.enemy_skill_id else None
    meta_p1 = get_player_skill_meta(conn, battle.player_id, skill_p1.id) if skill_p1 else None
    meta_p2 = get_player_skill_meta(conn, battle.enemy_player_id, skill_p2.id) if skill_p2 else None
    p1_level = meta_p1["level"] if meta_p1 else 1
    p2_level = meta_p2["level"] if meta_p2 else 1
    p1_multiplier = skill_p1.damage_multiplier * (1 + 0.05 * (p1_level - 1)) if skill_p1 else 1.0
    p2_multiplier = skill_p2.damage_multiplier * (1 + 0.05 * (p2_level - 1)) if skill_p2 else 1.0

    player_effects_rows = list_battle_effects(conn, battle.id, "player")
    enemy_effects_rows = list_battle_effects(conn, battle.id, "enemy")
    battle.player_hp, _ = apply_dot_effects(player_effects_rows, battle.player_hp)
    battle.enemy_hp, _ = apply_dot_effects(enemy_effects_rows, battle.enemy_hp)
    player_bonus = _build_bonus_from_effects(player_effects_rows)
    enemy_bonus = _build_bonus_from_effects(enemy_effects_rows)

    immediate_p1 = _apply_skill_effects(conn, battle.id, "enemy", skill_p1.effects_json) if skill_p1 else {"stamina_restore": 0, "move": 0, "ignore_def": 0, "damage_up": 0}
    immediate_p2 = _apply_skill_effects(conn, battle.id, "player", skill_p2.effects_json) if skill_p2 else {"stamina_restore": 0, "move": 0, "ignore_def": 0, "damage_up": 0}
    player_bonus["ignore_def_pct"] = immediate_p1["ignore_def"]
    enemy_bonus["ignore_def_pct"] = immediate_p2["ignore_def"]
    player_bonus["damage_pct"] = player_bonus.get("damage_pct", 0.0) + immediate_p1["damage_up"]
    enemy_bonus["damage_pct"] = enemy_bonus.get("damage_pct", 0.0) + immediate_p2["damage_up"]
    battle.player_stamina = clamp_stamina(battle.player_stamina + immediate_p1["stamina_restore"])
    battle.enemy_stamina = clamp_stamina(battle.enemy_stamina + immediate_p2["stamina_restore"])

    tags_p1 = json.loads(skill_p1.combo_tags_json) if skill_p1 and skill_p1.combo_tags_json else []
    tags_p2 = json.loads(skill_p2.combo_tags_json) if skill_p2 and skill_p2.combo_tags_json else []
    combo_state_p1 = load_combo_state(battle.player_combo_json)
    combo_state_p2 = load_combo_state(battle.enemy_combo_json)
    combo_state_p1, combo_result_p1 = apply_combo(combo_state_p1, tags_p1, SKILL)
    combo_state_p2, combo_result_p2 = apply_combo(combo_state_p2, tags_p2, SKILL)
    battle.player_combo_json = dump_combo_state(combo_state_p1)
    battle.enemy_combo_json = dump_combo_state(combo_state_p2)
    if combo_result_p1.get("finisher_effect"):
        fin = combo_result_p1["finisher_effect"]
        upsert_battle_effect(conn, battle.id, "enemy", fin["type"], fin["value"], fin["duration"], fin["max_stacks"])
    if combo_result_p2.get("finisher_effect"):
        fin = combo_result_p2["finisher_effect"]
        upsert_battle_effect(conn, battle.id, "player", fin["type"], fin["value"], fin["duration"], fin["max_stacks"])
    player_bonus["damage_pct"] = player_bonus.get("damage_pct", 0.0) + combo_result_p1.get("bonus_damage_pct", 0)
    enemy_bonus["damage_pct"] = enemy_bonus.get("damage_pct", 0.0) + combo_result_p2.get("bonus_damage_pct", 0)
    combo_text = f"🔗 Комбо: Игрок {combo_state_p1['steps']} | Противник {combo_state_p2['steps']}"

    p1_def = int(p1.defense * (1 + player_bonus.get("def_pct", 0.0) / 100))
    p2_def = int(p2.defense * (1 + enemy_bonus.get("def_pct", 0.0) / 100))
    player_state = FighterState(
        name=p1.username,
        hp=battle.player_hp,
        stamina=battle.player_stamina,
        atk=p1.attack,
        defense=p1_def,
        luck=p1.luck,
        max_hp=p1.hp,
    )
    enemy_state = FighterState(
        name=p2.username,
        hp=battle.enemy_hp,
        stamina=battle.enemy_stamina,
        atk=p2.attack,
        defense=p2_def,
        luck=p2.luck,
        max_hp=p2.hp,
    )

    (
        _enemy_action,
        log_entry,
        player_hp,
        player_sta,
        enemy_hp,
        enemy_sta,
        player_dead,
        enemy_dead,
        new_position,
    ) = process_pvp_turn(
        player_action=battle.player_action,
        enemy_action=battle.enemy_action,
        player=player_state,
        enemy=enemy_state,
        battle_turn=battle.turn,
        position=battle.position,
        player_bonus=player_bonus,
        enemy_bonus=enemy_bonus,
        player_status_text=summarize_effects(player_effects_rows),
        enemy_status_text=summarize_effects(enemy_effects_rows),
        combo_text=combo_text,
        player_skill_cost=skill_p1.stamina_cost if skill_p1 else None,
        enemy_skill_cost=skill_p2.stamina_cost if skill_p2 else None,
        player_skill_multiplier=p1_multiplier,
        enemy_skill_multiplier=p2_multiplier,
    )

    move_delta = int(immediate_p1["move"]) + int(immediate_p2["move"])
    if move_delta:
        new_position = _shift_position_by_delta(new_position, move_delta)

    battle.turn += 1
    battle.player_action = None
    battle.enemy_action = None
    battle.player_skill_id = None
    battle.enemy_skill_id = None
    battle.player_hp = player_hp
    battle.player_stamina = player_sta
    battle.enemy_hp = enemy_hp
    battle.enemy_stamina = enemy_sta
    battle.position = new_position
    battle.log = templates.trim_battle_log((battle.log + "\n\n" + log_entry).strip())

    if player_dead or enemy_dead:
        battle.status = "win"
        update_player_battle(conn, battle.player_id, None)
        update_player_battle(conn, battle.enemy_player_id, None)
        result_text = "🏁 Дуэль завершена."
    else:
        result_text = "⚔️ Дуэль продолжается."

    tick_battle_effects(conn, battle.id)
    update_battle(conn, battle)
    await _send_battle_message(
        callback.message,
        conn,
        battle.id,
        f"{log_entry}\n\n{result_text}",
    )
    if battle.status == "active":
        await _send_battle_message(
            callback.message,
            conn,
            battle.id,
            "🎯 Выбери действие:",
            reply_markup=battle_keyboard(),
        )
    await callback.answer()
    conn.close()
