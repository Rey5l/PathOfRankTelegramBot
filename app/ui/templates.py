from app.combat.formulas import ATTACK, DEFEND, DODGE, SKILL, SKIP


ACTION_LABELS = {
    ATTACK: "⚔️ Атака",
    DEFEND: "🛡 Защита",
    SKILL: "💥 Навык",
    DODGE: "🏃 Уклонение",
    SKIP: "⏸ Пропуск",
}

RARITY_EMOJI = {
    "COMMON": "⚪",
    "RARE": "🔵",
    "EPIC": "🟣",
    "LEGENDARY": "🟡",
}


def round_header(turn: int) -> str:
    return f"🌀 Раунд {turn}"


def round_separator() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def distance_visual(position: str) -> str:
    if position == "close":
        return "🧍—🧍"
    if position == "far":
        return "🧍———🧍"
    return "🧍——🧍"


def position_label(position: str) -> str:
    if position == "close":
        return "Ближняя"
    if position == "far":
        return "Дальняя"
    return "Средняя"


def range_label(range_key: str) -> str:
    if range_key == "MELEE":
        return "Ближняя"
    if range_key == "LONG":
        return "Дальняя"
    return "Средняя"


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def rarity_label(rarity: str) -> str:
    return RARITY_EMOJI.get(rarity, "⚪")


def skill_list_header() -> str:
    return "📘 Твои навыки"


def skill_list_item(name: str, rarity: str, range_label: str, level: int) -> str:
    return f"{rarity_label(rarity)} {name} Lv.{level} · {range_label}"


def skill_info_text(
    name: str,
    skill_type: str,
    stamina_cost: int,
    damage_multiplier: float,
    range_label: str,
    effect: str,
    rarity: str,
    description: str,
    level: int,
    copies: int,
) -> str:
    return (
        f"📕 Навык: {name}\n"
        f"🎯 Тип: {skill_type}\n"
        f"⚡ STA: {stamina_cost}\n"
        f"🗡 Множитель: {damage_multiplier}\n"
        f"📏 Дальность: {range_label}\n"
        f"✨ Эффект: {effect}\n"
        f"{rarity_label(rarity)} Редкость: {rarity}\n"
        f"📈 Уровень: {level} (осколки: {copies}/3)\n"
        f"📝 Описание: {description}"
    )


def trim_battle_log(log_text: str, keep_rounds: int = 2) -> str:
    if not log_text.strip():
        return log_text
    marker = "🌀 Раунд"
    if marker not in log_text:
        return log_text
    chunks = log_text.split(marker)
    rounds = []
    for chunk in chunks[1:]:
        rounds.append(f"{marker}{chunk}".strip())
    trimmed = rounds[-keep_rounds:]
    return "\n\n".join(trimmed)


def case_list_header() -> str:
    return "🎁 Твои кейсы"


def case_list_item(name: str, qty: int, description: str) -> str:
    return f"📦 {name} x{qty} — {description}"


def case_open_result(name: str, skills: list[str]) -> str:
    if not skills:
        return f"🫥 {name} оказался пустым."
    lines = [f"🎉 Открыт {name}!", "Ты получил:"]
    for skill in skills:
        lines.append(f"• {skill}")
    return "\n".join(lines)


def shop_header(gold: int) -> str:
    return f"🛒 Магазин кейсов | 💰 Золото: {gold}"


def shop_item(name: str, price: int, description: str) -> str:
    return f"📦 {name} — {price}💰\n{description}"


def shop_purchase_ok(name: str, gold_left: int) -> str:
    return f"✅ Куплен кейс: {name}\n💰 Остаток: {gold_left}"


def shop_purchase_fail() -> str:
    return "❌ Недостаточно золота или кейс не найден."


def top_header() -> str:
    return "🏆 Топ авантюристов"


def top_entry(index: int, username: str, rank: str, level: int, xp: int) -> str:
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, "🔸")
    return f"{medal} {index}. {username} | Ранг {rank} | Ур. {level} | XP {xp}"
