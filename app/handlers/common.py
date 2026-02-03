from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import state
from app.keyboards import skills_inline_keyboard
from app.progression import xp_to_next_level
from app.ui import templates
from app.db import create_player, get_connection, get_player_by_telegram, list_top_players


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player:
        username = message.from_user.username or f"user_{message.from_user.id}"
        player = create_player(conn, message.from_user.id, username)
        greet = "🏰 Добро пожаловать в Гильдию авантюристов! Регистрация завершена."
    else:
        greet = "✨ С возвращением, авантюрист."

    commands = (
        "📜 Доступные команды:\n"
        "🧭 /me — профиль\n"
        "🗺 /quest — взять контракт\n"
        "⚔️ /battle — текущий бой\n"
        "🛒 /shop — магазин кейсов\n"
        "🎁 /cases — кейсы\n"
        "📘 /skills — навыки\n"
        "🤝 /duel @user — дуэль (MVP)\n"
        "🏆 /top — рейтинг\n"
        "ℹ️ /help — помощь"
    )
    await message.answer(f"{greet}\n\n{commands}")
    conn.close()


@router.message(Command("me"))
async def cmd_me(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player:
        await message.answer("Сначала зарегистрируйся через /start.")
        conn.close()
        return
    next_xp = xp_to_next_level(player.level)
    xp_left = max(0, next_xp - player.xp)
    text = (
        f"🧝 Профиль {player.username}\n"
        f"🏅 Ранг: {player.rank}\n"
        f"⭐ Уровень: {player.level} | XP: {player.xp}/{next_xp} (до уровня: {xp_left})\n"
        f"💰 Золото: {player.gold}\n"
        f"❤️ HP: {player.hp} | ⚡ STA: {player.stamina}\n"
        f"🗡 ATK: {player.attack} | 🛡 DEF: {player.defense} | 🍀 LUCK: {player.luck}"
    )
    await message.answer(text, reply_markup=skills_inline_keyboard())
    conn.close()


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    players = list_top_players(conn, limit=10)
    if not players:
        await message.answer("🏆 Рейтинг пока пуст.")
        conn.close()
        return
    lines = [templates.top_header()]
    for idx, player in enumerate(players, start=1):
        lines.append(
            templates.top_entry(idx, player.username, player.rank, player.level, player.xp)
        )
    await message.answer("\n".join(lines))
    conn.close()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "📜 Команды:\n"
        "🏰 /start — регистрация\n"
        "🧭 /me — профиль\n"
        "🗺 /quest — взять контракт\n"
        "⚔️ /battle — текущий бой\n"
        "🛒 /shop — магазин кейсов\n"
        "🎁 /cases — кейсы\n"
        "📘 /skills — навыки\n"
        "🤝 /duel @user — дуэль (MVP)\n"
        "🏆 /top — рейтинг\n"
        "ℹ️ /help — помощь"
    )
    await message.answer(text)
