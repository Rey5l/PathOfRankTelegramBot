from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

from app import state
from app.combat.engine import FighterState, process_pve_turn, process_pvp_turn
from app.combat.formulas import ATTACK, DEFEND, DODGE, SKILL, SKIP
from app.db import (
    add_battle_message,
    delete_battle_message,
    get_battle,
    get_connection,
    get_monster_by_id,
    get_player_by_id,
    get_player_by_telegram,
    list_battle_messages,
    reward_player,
    update_battle,
    update_player_battle,
)
from app.keyboards import battle_keyboard
from app.ui import templates
from app.cases import roll_quest_case_drop
from app.db import grant_case


router = Router()
KEEP_BATTLE_MESSAGES = 2


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

    if battle.type == "PVE":
        monster = get_monster_by_id(conn, battle.monster_id)
        player_state = FighterState(
            name=player.username,
            hp=battle.player_hp,
            stamina=battle.player_stamina,
            atk=player.attack,
            defense=player.defense,
            luck=player.luck,
            max_hp=player.hp,
        )
        monster_state = FighterState(
            name=monster.name,
            hp=battle.enemy_hp,
            stamina=battle.enemy_stamina,
            atk=monster.atk,
            defense=monster.defense,
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
            side_label = "Игрок"
        else:
            battle.enemy_action = action
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

        player_state = FighterState(
            name=p1.username,
            hp=battle.player_hp,
            stamina=battle.player_stamina,
            atk=p1.attack,
            defense=p1.defense,
            luck=p1.luck,
            max_hp=p1.hp,
        )
        enemy_state = FighterState(
            name=p2.username,
            hp=battle.enemy_hp,
            stamina=battle.enemy_stamina,
            atk=p2.attack,
            defense=p2.defense,
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
