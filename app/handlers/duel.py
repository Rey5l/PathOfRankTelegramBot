from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import state
from app.db import (
    create_pvp_battle,
    get_connection,
    get_player_by_telegram,
    get_player_by_username,
)


router = Router()


@router.message(Command("duel"))
async def cmd_duel(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player:
        await message.answer("Сначала зарегистрируйся через /start.")
        conn.close()
        return

    if player.current_battle_id:
        await message.answer("У тебя уже есть активный бой.")
        conn.close()
        return

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].startswith("@"):
        await message.answer("Использование: /duel @username")
        conn.close()
        return

    enemy_username = parts[1].lstrip("@")
    enemy = get_player_by_username(conn, enemy_username)
    if not enemy:
        await message.answer("Игрок не найден.")
        conn.close()
        return
    if enemy.current_battle_id:
        await message.answer("Этот игрок уже в бою.")
        conn.close()
        return

    create_pvp_battle(conn, player, enemy)
    await message.answer(
        f"Дуэль началась с @{enemy.username}. Оба игрока могут открыть /battle."
    )
    conn.close()
