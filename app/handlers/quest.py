from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import state
from app.db import (
    create_pve_battle,
    get_connection,
    get_monster_by_rank,
    get_player_by_telegram,
    update_player_battle,
)


router = Router()


@router.message(Command("quest"))
async def cmd_quest(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player:
        await message.answer("🏰 Сначала зарегистрируйся через /start.")
        conn.close()
        return

    if player.current_battle_id:
        await message.answer("⚔️ У тебя уже есть активный бой. Используй /battle.")
        conn.close()
        return

    monster = get_monster_by_rank(conn, player.rank)
    battle = create_pve_battle(conn, player, monster)

    text = (
        "📝 Контракт принят!\n"
        f"👹 Противник: {monster.name} (Ранг {monster.rank})\n"
        f"❤️ HP: {battle.enemy_hp} | 🗡 ATK: {monster.atk} | 🛡 DEF: {monster.defense}\n"
        "⚔️ Используй /battle для начала."
    )
    await message.answer(text)
    conn.close()
