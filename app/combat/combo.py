import json


def default_combo_state() -> dict:
    return {"active": False, "steps": 0, "remaining": 0}


def load_combo_state(raw: str) -> dict:
    if not raw:
        return default_combo_state()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {
                "active": bool(data.get("active", False)),
                "steps": int(data.get("steps", 0)),
                "remaining": int(data.get("remaining", 0)),
            }
    except json.JSONDecodeError:
        pass
    return default_combo_state()


def dump_combo_state(state: dict) -> str:
    return json.dumps(state)


def apply_combo(
    state: dict,
    tags: list[str],
    action: str,
) -> tuple[dict, dict]:
    result = {"bonus_damage_pct": 0, "finisher_effect": None}
    if action != "SKILL":
        return default_combo_state(), result

    if "STARTER" in tags and not state.get("active"):
        return {"active": True, "steps": 1, "remaining": 2}, result

    if state.get("active") and state.get("remaining", 0) > 0:
        if "LINK" in tags:
            state["steps"] += 1
            state["remaining"] -= 1
            return state, result
        if "FINISH" in tags:
            state["steps"] += 1
            state["remaining"] -= 1
            result["bonus_damage_pct"] = 25
            result["finisher_effect"] = {"type": "stun", "value": 1, "duration": 1, "stacks": 1, "max_stacks": 1, "target": "enemy"}
            return default_combo_state(), result

    return default_combo_state(), result
