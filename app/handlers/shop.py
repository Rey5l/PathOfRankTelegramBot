from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import state
from app.db import (
    buy_case,
    buy_case_by_id,
    get_connection,
    get_player_by_id,
    get_player_by_telegram,
    list_shop_cases,
)
from app.keyboards import shop_keyboard
from app.ui import templates


router = Router()


@router.message(Command("shop"))
async def cmd_shop(message: Message) -> None:
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
    if len(parts) >= 3 and parts[1].lower() == "buy":
        case_name = parts[2]
        ok = buy_case(conn, player.id, case_name)
        if ok:
            updated = get_player_by_id(conn, player.id)
            gold_left = updated.gold if updated else player.gold
            await message.answer(templates.shop_purchase_ok(case_name, gold_left))
        else:
            await message.answer(templates.shop_purchase_fail())
        conn.close()
        return

    cases = list_shop_cases(conn)
    lines = [templates.shop_header(player.gold)]
    for case in cases:
        lines.append(templates.shop_item(case["name"], case["price"], case["description"]))
    lines.append("ℹ️ Купить: /shop buy Название или кнопкой ниже")
    await message.answer(
        "\n\n".join(lines),
        reply_markup=shop_keyboard(cases),
    )
    conn.close()


@router.callback_query(lambda c: c.data and c.data.startswith("shop:buy:"))
async def callback_shop_buy(callback: CallbackQuery) -> None:
    if not state.db_path:
        await callback.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, callback.from_user.id)
    if not player:
        await callback.answer("Сначала /start.")
        conn.close()
        return
    case_id = int(callback.data.split(":")[2])
    case_name = None
    for case in list_shop_cases(conn):
        if case["id"] == case_id:
            case_name = case["name"]
            break
    ok = buy_case_by_id(conn, player.id, case_id)
    if ok:
        updated = get_player_by_id(conn, player.id)
        gold_left = updated.gold if updated else player.gold
        await callback.message.answer(
            templates.shop_purchase_ok(case_name or "Кейс", gold_left)
        )
    else:
        await callback.message.answer(templates.shop_purchase_fail())
    await callback.answer()
    conn.close()
