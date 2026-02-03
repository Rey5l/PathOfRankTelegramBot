from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import state
from app.db import get_connection, get_player_by_telegram, list_cases_for_player, open_case
from app.ui import templates


router = Router()


@router.message(Command("cases"))
async def cmd_cases(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player:
        await message.answer("🏰 Сначала зарегистрируйся через /start.")
        conn.close()
        return

    cases = list_cases_for_player(conn, player.id)
    if not cases:
        await message.answer("🎁 У тебя пока нет кейсов.")
        conn.close()
        return

    lines = [templates.case_list_header()]
    for case in cases:
        lines.append(
            templates.case_list_item(case["name"], case["quantity"], case["description"])
        )
    lines.append("ℹ️ Открыть: /case open Название")
    await message.answer("\n".join(lines))
    conn.close()


@router.message(Command("case"))
async def cmd_case(message: Message) -> None:
    if not state.db_path:
        await message.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, message.from_user.id)
    if not player:
        await message.answer("🏰 Сначала зарегистрируйся через /start.")
        conn.close()
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or parts[1].lower() != "open":
        await message.answer("Использование: /case open Название")
        conn.close()
        return

    case_name = parts[2]
    rewards = open_case(conn, player.id, case_name)
    if rewards is None:
        await message.answer("Кейс не найден или закончился.")
        conn.close()
        return

    if not rewards:
        await message.answer("🎁 Кейс открыт, но новых навыков не выпало.")
        conn.close()
        return

    reward_names = [r.name for r in rewards]
    await message.answer(templates.case_open_result(case_name, reward_names))
    conn.close()
