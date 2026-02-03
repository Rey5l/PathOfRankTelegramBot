import json
import random
import sqlite3

from app.models import Skill


def _weighted_choice(weights: dict[str, float]) -> str:
    items = list(weights.items())
    total = sum(w for _, w in items)
    roll = random.uniform(0, total)
    acc = 0.0
    for key, weight in items:
        acc += weight
        if roll <= acc:
            return key
    return items[-1][0]


def _list_skills_by_rarity(
    conn: sqlite3.Connection,
    rarity: str,
    allow_hidden: bool,
    exclude_ids: set[int],
) -> list[Skill]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, type, stamina_cost, damage_multiplier,
               range, effect, rarity, hidden, description
        FROM skills
        WHERE rarity = ? AND (? = 1 OR hidden = 0)
        """,
        (rarity, 1 if allow_hidden else 0),
    )
    rows = cursor.fetchall()
    return [Skill(**row) for row in rows if row["id"] not in exclude_ids]


def roll_case_rewards(
    conn: sqlite3.Connection, player_id: int, case_row: sqlite3.Row
) -> list[Skill]:
    weights = json.loads(case_row["weights_json"])
    rolls = random.randint(case_row["min_rolls"], case_row["max_rolls"])
    allow_hidden = bool(case_row["allow_hidden"])

    rewards: list[Skill] = []
    exclude_ids: set[int] = set()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT skill_id FROM player_skills WHERE player_id = ? AND is_unlocked = 1",
        (player_id,),
    )
    exclude_ids.update(row["skill_id"] for row in cursor.fetchall())

    for _ in range(rolls):
        available_pools: dict[str, list[Skill]] = {}
        for rarity_key in weights.keys():
            pool = _list_skills_by_rarity(conn, rarity_key, allow_hidden, exclude_ids)
            if pool:
                available_pools[rarity_key] = pool
        if not available_pools:
            # Если все навыки уже открыты, разрешаем дубликаты.
            exclude_ids.clear()
            for rarity_key in weights.keys():
                pool = _list_skills_by_rarity(conn, rarity_key, allow_hidden, exclude_ids)
                if pool:
                    available_pools[rarity_key] = pool
        if not available_pools:
            break
        filtered_weights = {k: weights[k] for k in available_pools.keys()}
        rarity = _weighted_choice(filtered_weights)
        pool = available_pools[rarity]
        skill = random.choice(pool)
        rewards.append(skill)
        exclude_ids.add(skill.id)

    return rewards


def roll_quest_case_drop(player_rank: str) -> str | None:
    rank_letter = player_rank[0] if player_rank else "F"
    roll = random.random()
    if roll < 0.10:
        return "Novice Case"
    if rank_letter in {"C", "B", "A", "S"} and roll < 0.14:
        return "Hunter Case"
    return None
