from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.combat.formulas import ATTACK, DEFEND, DODGE, SKILL, SKIP
from app.ui.templates import action_label


def battle_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    actions = [ATTACK, DEFEND, SKILL, DODGE, SKIP]
    for action in actions:
        builder.add(
            InlineKeyboardButton(text=action_label(action), callback_data=f"battle:{action}")
        )
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def shop_keyboard(cases: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for case in cases:
        builder.add(
            InlineKeyboardButton(
                text=f"Купить {case['name']} ({case['price']}💰)",
                callback_data=f"shop:buy:{case['id']}",
            )
        )
    builder.adjust(1)
    return builder.as_markup()


def skills_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="📘 Навыки", callback_data="skills:open")
    )
    return builder.as_markup()
