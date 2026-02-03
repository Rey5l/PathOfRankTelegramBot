import json
from typing import Iterable


def parse_effects_json(effects_json: str) -> list[dict]:
    try:
        data = json.loads(effects_json)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        return []
    return []


def summarize_effects(effects: Iterable) -> str:
    if not effects:
        return "нет"
    parts = []
    for eff in effects:
        if isinstance(eff, dict):
            name = eff.get("type") or eff.get("effect_type")
            duration = eff.get("duration", 0)
            stacks = eff.get("stacks", 1)
        else:
            name = eff["effect_type"]
            duration = eff["duration"]
            stacks = eff["stacks"]
        parts.append(f"{name}({duration}х, ст: {stacks})")
    return ", ".join(parts)


def effects_to_modifiers(effects: Iterable[dict]) -> dict:
    mods = {
        "def_pct": 0.0,
        "dodge_pct": 0.0,
        "crit_pct": 0.0,
        "damage_pct": 0.0,
        "stunned": False,
    }
    for eff in effects:
        etype = eff.get("effect_type") or eff.get("type")
        value = float(eff.get("value", 0))
        stacks = int(eff.get("stacks", 1))
        if etype == "def_down":
            mods["def_pct"] -= value * stacks
        elif etype == "def_up":
            mods["def_pct"] += value * stacks
        elif etype == "dodge_up":
            mods["dodge_pct"] += value * stacks
        elif etype == "dodge_down":
            mods["dodge_pct"] -= value * stacks
        elif etype == "crit_up":
            mods["crit_pct"] += value * stacks
        elif etype == "crit_down":
            mods["crit_pct"] -= value * stacks
        elif etype == "damage_up":
            mods["damage_pct"] += value * stacks
        elif etype == "stun":
            mods["stunned"] = True
    return mods


def apply_dot_effects(effects: Iterable, hp: int) -> tuple[int, int]:
    total = 0
    for eff in effects:
        if isinstance(eff, dict):
            etype = eff.get("effect_type") or eff.get("type")
            value = int(eff.get("value", 0))
            stacks = int(eff.get("stacks", 1))
        else:
            etype = eff["effect_type"]
            value = int(eff["value"])
            stacks = int(eff["stacks"])
        if etype in {"bleed", "burn"}:
            total += value * stacks
    new_hp = max(0, hp - total)
    return new_hp, total
