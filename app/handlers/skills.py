from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app import state
from app.db import (
    get_connection,
    get_player_by_telegram,
    get_skill_by_name,
    get_player_skill_meta,
    list_player_skills,
    player_has_skill,
)
from app.ui import templates


router = Router()


def _skills_list_text(skills) -> str:
    lines = [templates.skill_list_header()]
    for skill in skills:
        lines.append(
            templates.skill_list_item(
                name=skill.name,
                rarity=skill.rarity,
                range_label=templates.range_label(skill.range),
                level=skill.level,
            )
        )
    lines.append("ℹ️ Для деталей: /skills info Название")
    return "\n".join(lines)


@router.message(Command("skills"))
async def cmd_skills(message: Message) -> None:
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
    if len(parts) >= 2 and parts[1].lower() == "info":
        if len(parts) < 3:
            await message.answer("Использование: /skills info Название")
            conn.close()
            return
        name = parts[2]
        skill = get_skill_by_name(conn, name)
        if not skill:
            await message.answer("Навык не найден.")
            conn.close()
            return
        if skill.hidden and not player_has_skill(conn, player.id, skill.id):
            await message.answer("🔒 Этот навык пока недоступен.")
            conn.close()
            return
        meta = get_player_skill_meta(conn, player.id, skill.id)
        level = meta["level"] if meta else 1
        copies = meta["copies"] if meta else 0
        await message.answer(
            templates.skill_info_text(
                name=skill.name,
                skill_type=skill.type,
                stamina_cost=skill.stamina_cost,
                damage_multiplier=skill.damage_multiplier,
                range_label=templates.range_label(skill.range),
                effect=skill.effect,
                rarity=skill.rarity,
                description=skill.description,
                level=level,
                copies=copies,
            )
        )
        conn.close()
        return

    skills = list_player_skills(conn, player.id)
    if not skills:
        await message.answer("📘 У тебя пока нет навыков.")
        conn.close()
        return
    await message.answer(_skills_list_text(skills))
    conn.close()


@router.callback_query(lambda c: c.data == "skills:open")
async def callback_skills_open(callback: CallbackQuery) -> None:
    if not state.db_path:
        await callback.answer("Ошибка конфигурации БД.")
        return
    conn = get_connection(state.db_path)
    player = get_player_by_telegram(conn, callback.from_user.id)
    if not player:
        await callback.answer("Сначала /start.")
        conn.close()
        return
    skills = list_player_skills(conn, player.id)
    if not skills:
        await callback.message.answer("📘 У тебя пока нет навыков.")
        await callback.answer()
        conn.close()
        return
    await callback.message.answer(_skills_list_text(skills))
    await callback.answer()
    conn.close()
