import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional

from app.models import Battle, Case, Monster, Player, Skill
from app.progression import apply_leveling, level_stat_growth, rank_from_level
from app.cases import roll_case_rewards


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT NOT NULL,
            rank TEXT NOT NULL,
            level INTEGER NOT NULL,
            xp INTEGER NOT NULL,
            gold INTEGER NOT NULL,
            hp INTEGER NOT NULL,
            stamina INTEGER NOT NULL,
            attack INTEGER NOT NULL,
            defense INTEGER NOT NULL,
            luck INTEGER NOT NULL,
            current_battle_id INTEGER
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monsters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rank TEXT NOT NULL,
            hp INTEGER NOT NULL,
            atk INTEGER NOT NULL,
            defense INTEGER NOT NULL,
            behavior_type TEXT NOT NULL,
            reward_xp INTEGER NOT NULL,
            reward_gold INTEGER NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            turn INTEGER NOT NULL,
            player_action TEXT,
            enemy_action TEXT,
            log TEXT NOT NULL,
            status TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            monster_id INTEGER,
            enemy_player_id INTEGER,
            player_hp INTEGER NOT NULL,
            player_stamina INTEGER NOT NULL,
            enemy_hp INTEGER NOT NULL,
            enemy_stamina INTEGER NOT NULL,
            position TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            stamina_cost INTEGER NOT NULL,
            damage_multiplier REAL NOT NULL,
            range TEXT NOT NULL,
            effect TEXT NOT NULL,
            rarity TEXT NOT NULL,
            hidden INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS battle_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            min_rolls INTEGER NOT NULL,
            max_rolls INTEGER NOT NULL,
            weights_json TEXT NOT NULL,
            allow_hidden INTEGER NOT NULL DEFAULT 0,
            price INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS player_cases (
            player_id INTEGER NOT NULL,
            case_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (player_id, case_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    _ensure_battle_columns(conn)
    _ensure_skill_columns(conn)
    _ensure_player_skills_table(conn)
    _ensure_case_columns(conn)
    conn.commit()
    seed_data(conn)
    _dedupe_skills_by_name(conn)
    _maybe_resync_skills(conn)
    _ensure_case_prices(conn)
    conn.close()


def _ensure_battle_columns(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(battles)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "position" not in columns:
        cursor.execute(
            "ALTER TABLE battles ADD COLUMN position TEXT NOT NULL DEFAULT 'medium'"
        )


def _ensure_skill_columns(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(skills)")
    columns = {row["name"] for row in cursor.fetchall()}
    required = {
        "type": "TEXT NOT NULL DEFAULT 'ATTACK'",
        "range": "TEXT NOT NULL DEFAULT 'MID'",
        "effect": "TEXT NOT NULL DEFAULT ''",
        "rarity": "TEXT NOT NULL DEFAULT 'COMMON'",
        "hidden": "INTEGER NOT NULL DEFAULT 0",
        "description": "TEXT NOT NULL DEFAULT ''",
    }
    for name, ddl in required.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE skills ADD COLUMN {name} {ddl}")


def _ensure_player_skills_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS player_skills (
            player_id INTEGER NOT NULL,
            skill_id INTEGER NOT NULL,
            is_unlocked INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (player_id, skill_id)
        )
        """
    )


def _ensure_case_columns(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(cases)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "price" not in columns:
        cursor.execute("ALTER TABLE cases ADD COLUMN price INTEGER NOT NULL DEFAULT 0")


def seed_data(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM monsters")
    if cursor.fetchone()["cnt"] == 0:
        monsters = [
            ("Песчаный слизень", "F", 60, 8, 4, "aggressive", 20, 15),
            ("Лесной волк", "F", 70, 10, 5, "trickster", 24, 18),
            ("Костяной страж", "D", 120, 16, 10, "defensive", 45, 40),
            ("Болотный тролль", "C", 180, 22, 14, "berserk", 80, 65),
            ("Кровавый рыцарь", "B", 240, 30, 18, "aggressive", 130, 110),
            ("Дракон-страж", "A", 320, 40, 24, "berserk", 200, 180),
            ("Тень древних", "S", 420, 52, 30, "stamina_drain", 320, 280),
        ]
        cursor.executemany(
            """
            INSERT INTO monsters (name, rank, hp, atk, defense, behavior_type, reward_xp, reward_gold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            monsters,
        )
    skills = [
            (
                "Power Strike",
                "ATTACK",
                20,
                1.5,
                "MELEE",
                "Оглушение на 1 ход (20% шанс).",
                "COMMON",
                0,
                "Сильный удар на ближней дистанции.",
            ),
            (
                "Twin Slash",
                "ATTACK",
                18,
                1.3,
                "MELEE",
                "Кровотечение на 2 хода.",
                "COMMON",
                0,
                "Два быстрых разреза.",
            ),
            (
                "Piercing Shot",
                "ATTACK",
                22,
                1.4,
                "LONG",
                "Игнорирует 20% DEF цели.",
                "RARE",
                0,
                "Дальний выстрел по слабому месту.",
            ),
            (
                "Whirlwind",
                "ATTACK",
                26,
                1.6,
                "MELEE",
                "Снижает DEF цели на 10% на 2 хода.",
                "RARE",
                0,
                "Вихревой удар по площади.",
            ),
            (
                "Seismic удар",
                "ATTACK",
                30,
                1.8,
                "MID",
                "Отбрасывает цель на 1 позицию.",
                "EPIC",
                0,
                "Сильный удар с ударной волной.",
            ),
            (
                "Shadow Lunge",
                "ATTACK",
                28,
                1.7,
                "MID",
                "Сближает на 1 позицию и даёт +10% крит.",
                "EPIC",
                1,
                "Скрытый выпад из тени. Открывается после победы над 10 монстрами.",
            ),
            (
                "Iron Wall",
                "DEFENSE",
                15,
                0.8,
                "MELEE",
                "Снижает урон на 30% в этом ходу.",
                "COMMON",
                0,
                "Глухая оборона.",
            ),
            (
                "Mirror Guard",
                "DEFENSE",
                20,
                0.9,
                "MID",
                "Шанс отразить 20% урона.",
                "RARE",
                0,
                "Защита с отражением.",
            ),
            (
                "Evasion Step",
                "DEFENSE",
                18,
                0.7,
                "LONG",
                "Отступает на 1 позицию, +15% уклон.",
                "RARE",
                0,
                "Лёгкий шаг в сторону.",
            ),
            (
                "Fortress Stance",
                "DEFENSE",
                24,
                0.6,
                "MELEE",
                "Иммунитет к криту на 1 ход.",
                "EPIC",
                1,
                "Секретная стойка. Открывается при ранге B.",
            ),
            (
                "Second Wind",
                "SUPPORT",
                0,
                0.0,
                "MID",
                "Восстанавливает 25 STA.",
                "COMMON",
                0,
                "Восстановление дыхания.",
            ),
            (
                "Battle Focus",
                "SUPPORT",
                10,
                0.0,
                "MID",
                "Даёт +10% уклон и +10% крит на 2 хода.",
                "RARE",
                0,
                "Фокус и холодный разум.",
            ),
            (
                "Smoke Bomb",
                "SUPPORT",
                16,
                0.0,
                "LONG",
                "Увеличивает дистанцию на 1.",
                "RARE",
                0,
                "Дымовая завеса для отступления.",
            ),
            (
                "Blazing Uppercut",
                "ATTACK",
                24,
                1.45,
                "MELEE",
                "Подбрасывает цель, снижая её уклон на 10% на 1 ход.",
                "COMMON",
                0,
                "Мощный удар снизу с огненным следом.",
            ),
            (
                "Frost Lance",
                "ATTACK",
                26,
                1.55,
                "MID",
                "Замедляет цель: -10% шанс уклонения на 2 хода.",
                "RARE",
                0,
                "Ледяной выпад с контролем дистанции.",
            ),
            (
                "Ranger Volley",
                "ATTACK",
                28,
                1.6,
                "LONG",
                "Наносит урон и увеличивает дистанцию на 1.",
                "RARE",
                0,
                "Серия дальних выстрелов.",
            ),
            (
                "Crimson Edge",
                "ATTACK",
                32,
                1.8,
                "MELEE",
                "Усиливает кровотечение: +1 ход к длительности.",
                "EPIC",
                0,
                "Алый клинок оставляет глубокие раны.",
            ),
            (
                "Meteor Break",
                "ATTACK",
                36,
                2.0,
                "MID",
                "Снижает DEF цели на 20% на 2 хода.",
                "LEGENDARY",
                1,
                "Легендарный удар с небес. Открывается после ранга A.",
            ),
            (
                "Aegis Shift",
                "DEFENSE",
                18,
                0.7,
                "MID",
                "Снимает отрицательный эффект и даёт +10% DEF на 2 хода.",
                "COMMON",
                0,
                "Смена стойки, очищающая ауры.",
            ),
            (
                "Steel Pulse",
                "DEFENSE",
                22,
                0.6,
                "MELEE",
                "Отражает 10% урона и сдвигает позицию к средней.",
                "RARE",
                0,
                "Ритмичная стойка стража.",
            ),
            (
                "Guardian Halo",
                "DEFENSE",
                30,
                0.5,
                "MID",
                "Снижает входящий урон на 40% на 1 ход.",
                "EPIC",
                0,
                "Защитный барьер света.",
            ),
            (
                "Void Bastion",
                "DEFENSE",
                34,
                0.5,
                "MELEE",
                "Иммунитет к криту и -20% входящего урона на 1 ход.",
                "LEGENDARY",
                1,
                "Тёмная бастилия. Открывается после 5 побед над S-рангом.",
            ),
            (
                "Quick Reset",
                "SUPPORT",
                12,
                0.0,
                "MID",
                "Восстанавливает 15 STA и даёт +5% крит на 1 ход.",
                "COMMON",
                0,
                "Быстрое восстановление темпа.",
            ),
            (
                "Adrenal Rush",
                "SUPPORT",
                20,
                0.0,
                "MELEE",
                "Сближает на 1 позицию и даёт +15% урон на 1 ход.",
                "RARE",
                0,
                "Рывок с выбросом адреналина.",
            ),
            (
                "Arcane Surge",
                "SUPPORT",
                24,
                0.0,
                "LONG",
                "Восстанавливает 30 STA и даёт +10% уклон на 2 хода.",
                "EPIC",
                0,
                "Всплеск магической энергии.",
            ),
            (
                "Eclipse Pact",
                "SUPPORT",
                0,
                0.0,
                "MID",
                "Обнуляет STA, но даёт +30% крит и +20% урон на 1 ход.",
                "LEGENDARY",
                1,
                "Договор затмения. Открывается на ранге S.",
            ),
        ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO skills
        (name, type, stamina_cost, damage_multiplier, range, effect, rarity, hidden, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        skills,
    )
    conn.commit()
    _assign_defaults_to_existing_players(conn)
    _seed_cases(conn)


def _assign_defaults_to_existing_players(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM players")
    player_ids = [row["id"] for row in cursor.fetchall()]
    for player_id in player_ids:
        assign_default_skills(conn, player_id)
        grant_case(conn, player_id, "Novice Case", 1)


def _seed_cases(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM cases")
    if cursor.fetchone()["cnt"] > 0:
        return
    cases = [
        (
            "Novice Case",
            "Стартовый кейс новичка. Содержит COMMON навыки.",
            3,
            4,
            json.dumps({"COMMON": 1.0}),
            0,
            50,
        ),
        (
            "Hunter Case",
            "Награда за охоту. COMMON/RARE навыки.",
            3,
            5,
            json.dumps({"COMMON": 0.65, "RARE": 0.30, "EPIC": 0.05}),
            0,
            120,
        ),
        (
            "Champion Case",
            "Кейс чемпиона. RARE/EPIC навыки.",
            3,
            5,
            json.dumps({"RARE": 0.55, "EPIC": 0.35, "LEGENDARY": 0.10}),
            0,
            250,
        ),
        (
            "Shadow Case",
            "Теневой кейс. EPIC/LEGENDARY навыки.",
            4,
            5,
            json.dumps({"RARE": 0.05, "EPIC": 0.55, "LEGENDARY": 0.40}),
            1,
            500,
        ),
        (
            "Event Case",
            "Ивентовый кейс. RARE/EPIC/LEGENDARY навыки.",
            3,
            5,
            json.dumps({"RARE": 0.45, "EPIC": 0.40, "LEGENDARY": 0.15}),
            1,
            300,
        ),
    ]
    cursor.executemany(
        """
        INSERT INTO cases (name, description, min_rolls, max_rolls, weights_json, allow_hidden, price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        cases,
    )
    conn.commit()


def _ensure_case_prices(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    prices = {
        "Novice Case": 50,
        "Hunter Case": 120,
        "Champion Case": 250,
        "Shadow Case": 500,
        "Event Case": 300,
    }
    for name, price in prices.items():
        cursor.execute(
            """
            UPDATE cases
            SET price = ?
            WHERE name = ? AND (price IS NULL OR price = 0)
            """,
            (price, name),
        )
    conn.commit()


def create_player(conn: sqlite3.Connection, telegram_id: int, username: str) -> Player:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO players (telegram_id, username, rank, level, xp, gold, hp, stamina, attack, defense, luck, current_battle_id)
        VALUES (?, ?, 'F', 1, 0, 50, 100, 100, 12, 6, 5, NULL)
        """,
        (telegram_id, username),
    )
    conn.commit()
    player = get_player_by_telegram(conn, telegram_id)
    if player:
        assign_default_skills(conn, player.id)
        grant_case(conn, player.id, "Novice Case", 1)
    return player


def assign_default_skills(conn: sqlite3.Connection, player_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT level FROM players WHERE id = ?", (player_id,))
    row = cursor.fetchone()
    if not row:
        return
    skill_ids = _list_skills_by_level(conn, row["level"])
    cursor.executemany(
        """
        INSERT OR IGNORE INTO player_skills (player_id, skill_id, is_unlocked)
        VALUES (?, ?, 1)
        """,
        [(player_id, skill_id) for skill_id in skill_ids],
    )
    conn.commit()


def _list_skills_by_level(conn: sqlite3.Connection, level: int) -> list[int]:
    cursor = conn.cursor()
    thresholds = {
        "COMMON": 1,
        "RARE": 5,
        "EPIC": 10,
        "LEGENDARY": 15,
    }
    allowed = [rarity for rarity, min_level in thresholds.items() if level >= min_level]
    if not allowed:
        allowed = ["COMMON"]
    placeholders = ",".join("?" for _ in allowed)
    cursor.execute(
        f"""
        SELECT id FROM skills
        WHERE hidden = 0 AND rarity IN ({placeholders})
        """,
        allowed,
    )
    return [row["id"] for row in cursor.fetchall()]


def resync_player_skills_by_level(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT id, level FROM players")
    players = cursor.fetchall()
    for row in players:
        player_id = row["id"]
        cursor.execute("DELETE FROM player_skills WHERE player_id = ?", (player_id,))
        skill_ids = _list_skills_by_level(conn, row["level"])
        cursor.executemany(
            """
            INSERT INTO player_skills (player_id, skill_id, is_unlocked)
            VALUES (?, ?, 1)
            """,
            [(player_id, skill_id) for skill_id in skill_ids],
        )
    conn.commit()


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_meta WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row["value"] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


def _maybe_resync_skills(conn: sqlite3.Connection) -> None:
    if _get_meta(conn, "skills_resynced") == "1":
        return
    resync_player_skills_by_level(conn)
    _set_meta(conn, "skills_resynced", "1")


def _dedupe_skills_by_name(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name, MIN(id) as keep_id
        FROM skills
        GROUP BY name
        HAVING COUNT(*) > 1
        """
    )
    duplicates = cursor.fetchall()
    for row in duplicates:
        name = row["name"]
        keep_id = row["keep_id"]
        cursor.execute("SELECT id FROM skills WHERE name = ? AND id != ?", (name, keep_id))
        dup_ids = [r["id"] for r in cursor.fetchall()]
        for dup_id in dup_ids:
            cursor.execute(
                """
                UPDATE player_skills
                SET skill_id = ?
                WHERE skill_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM player_skills ps
                      WHERE ps.player_id = player_skills.player_id
                        AND ps.skill_id = ?
                  )
                """,
                (keep_id, dup_id, keep_id),
            )
            cursor.execute("DELETE FROM player_skills WHERE skill_id = ?", (dup_id,))
            cursor.execute("DELETE FROM skills WHERE id = ?", (dup_id,))
    conn.commit()


def get_player_by_telegram(conn: sqlite3.Connection, telegram_id: int) -> Optional[Player]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return Player(**row)


def get_player_by_id(conn: sqlite3.Connection, player_id: int) -> Optional[Player]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return Player(**row)


def get_player_by_username(conn: sqlite3.Connection, username: str) -> Optional[Player]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE username = ?", (username,))
    row = cursor.fetchone()
    if not row:
        return None
    return Player(**row)


def update_player_battle(conn: sqlite3.Connection, player_id: int, battle_id: Optional[int]) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE players SET current_battle_id = ? WHERE id = ?",
        (battle_id, player_id),
    )
    conn.commit()


def list_top_players(conn: sqlite3.Connection, limit: int = 10) -> list[Player]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM players ORDER BY level DESC, xp DESC LIMIT ?",
        (limit,),
    )
    rows = cursor.fetchall()
    return [Player(**row) for row in rows]


def get_monster_by_rank(conn: sqlite3.Connection, rank: str) -> Monster:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM monsters WHERE rank = ? ORDER BY RANDOM() LIMIT 1",
        (rank,),
    )
    row = cursor.fetchone()
    return Monster(**row)


def get_monster_by_id(conn: sqlite3.Connection, monster_id: int) -> Monster:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM monsters WHERE id = ?", (monster_id,))
    row = cursor.fetchone()
    return Monster(**row)


def get_battle(conn: sqlite3.Connection, battle_id: int) -> Optional[Battle]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM battles WHERE id = ?", (battle_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return Battle(**row)


def create_pve_battle(
    conn: sqlite3.Connection, player: Player, monster: Monster
) -> Battle:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO battles (type, turn, player_action, enemy_action, log, status, player_id, monster_id,
                             enemy_player_id, player_hp, player_stamina, enemy_hp, enemy_stamina, position)
        VALUES ('PVE', 1, NULL, NULL, '', 'active', ?, ?, NULL, ?, ?, ?, ?, 'medium')
        """,
        (
            player.id,
            monster.id,
            player.hp,
            player.stamina,
            monster.hp,
            100,
        ),
    )
    conn.commit()
    battle_id = cursor.lastrowid
    update_player_battle(conn, player.id, battle_id)
    return get_battle(conn, battle_id)


def create_pvp_battle(
    conn: sqlite3.Connection, player: Player, enemy: Player
) -> Battle:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO battles (type, turn, player_action, enemy_action, log, status, player_id, monster_id,
                             enemy_player_id, player_hp, player_stamina, enemy_hp, enemy_stamina, position)
        VALUES ('PVP', 1, NULL, NULL, '', 'active', ?, NULL, ?, ?, ?, ?, ?, 'medium')
        """,
        (
            player.id,
            enemy.id,
            player.hp,
            player.stamina,
            enemy.hp,
            enemy.stamina,
        ),
    )
    conn.commit()
    battle_id = cursor.lastrowid
    update_player_battle(conn, player.id, battle_id)
    update_player_battle(conn, enemy.id, battle_id)
    return get_battle(conn, battle_id)


def update_battle(conn: sqlite3.Connection, battle: Battle) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE battles
        SET turn = ?, player_action = ?, enemy_action = ?, log = ?, status = ?,
            player_hp = ?, player_stamina = ?, enemy_hp = ?, enemy_stamina = ?, position = ?
        WHERE id = ?
        """,
        (
            battle.turn,
            battle.player_action,
            battle.enemy_action,
            battle.log,
            battle.status,
            battle.player_hp,
            battle.player_stamina,
            battle.enemy_hp,
            battle.enemy_stamina,
            battle.position,
            battle.id,
        ),
    )
    conn.commit()


def reward_player(conn: sqlite3.Connection, player_id: int, xp: int, gold: int) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE players SET xp = xp + ?, gold = gold + ? WHERE id = ?",
        (xp, gold, player_id),
    )
    conn.commit()
    cursor.execute("SELECT level, xp FROM players WHERE id = ?", (player_id,))
    row = cursor.fetchone()
    if not row:
        return
    prev_level = row["level"]
    new_level, new_xp, levels_gained = apply_leveling(row["level"], row["xp"])
    new_rank = rank_from_level(new_level)
    growth = level_stat_growth(levels_gained)
    cursor.execute(
        """
        UPDATE players
        SET level = ?, xp = ?, rank = ?,
            hp = hp + ?, stamina = stamina + ?,
            attack = attack + ?, defense = defense + ?, luck = luck + ?
        WHERE id = ?
        """,
        (
            new_level,
            new_xp,
            new_rank,
            growth["hp"],
            growth["stamina"],
            growth["attack"],
            growth["defense"],
            growth["luck"],
            player_id,
        ),
    )
    conn.commit()
    if levels_gained > 0:
        for lvl in range(prev_level + 1, new_level + 1):
            grant_case(conn, player_id, "Novice Case", 1)
            if lvl % 5 == 0:
                grant_case(conn, player_id, "Hunter Case", 1)
            if lvl % 10 == 0:
                grant_case(conn, player_id, "Champion Case", 1)


def add_battle_message(
    conn: sqlite3.Connection, battle_id: int, chat_id: int, message_id: int
) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO battle_messages (battle_id, chat_id, message_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (battle_id, chat_id, message_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def list_battle_messages(conn: sqlite3.Connection, battle_id: int, chat_id: int) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, message_id
        FROM battle_messages
        WHERE battle_id = ? AND chat_id = ?
        ORDER BY id DESC
        """,
        (battle_id, chat_id),
    )
    return cursor.fetchall()


def delete_battle_message(conn: sqlite3.Connection, row_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM battle_messages WHERE id = ?", (row_id,))
    conn.commit()


def list_player_skills(conn: sqlite3.Connection, player_id: int) -> list[Skill]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.name, s.type, s.stamina_cost, s.damage_multiplier,
               s.range, s.effect, s.rarity, s.hidden, s.description
        FROM skills s
        JOIN player_skills ps ON ps.skill_id = s.id
        WHERE ps.player_id = ? AND ps.is_unlocked = 1
        ORDER BY s.rarity, s.name
        """,
        (player_id,),
    )
    rows = cursor.fetchall()
    return [Skill(**row) for row in rows]


def get_skill_by_name(conn: sqlite3.Connection, name: str) -> Skill | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, type, stamina_cost, damage_multiplier,
               range, effect, rarity, hidden, description
        FROM skills
        WHERE name = ?
        """,
        (name,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return Skill(**row)


def player_has_skill(conn: sqlite3.Connection, player_id: int, skill_id: int) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM player_skills
        WHERE player_id = ? AND skill_id = ? AND is_unlocked = 1
        """,
        (player_id, skill_id),
    )
    return cursor.fetchone() is not None


def list_cases_for_player(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.name, c.description, c.min_rolls, c.max_rolls, c.weights_json,
               c.allow_hidden, pc.quantity, c.price
        FROM cases c
        JOIN player_cases pc ON pc.case_id = c.id
        WHERE pc.player_id = ? AND pc.quantity > 0
        ORDER BY c.id
        """,
        (player_id,),
    )
    return cursor.fetchall()


def grant_case(conn: sqlite3.Connection, player_id: int, case_name: str, qty: int) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM cases WHERE name = ?", (case_name,))
    row = cursor.fetchone()
    if not row:
        return
    case_id = row["id"]
    cursor.execute(
        """
        INSERT INTO player_cases (player_id, case_id, quantity)
        VALUES (?, ?, ?)
        ON CONFLICT(player_id, case_id) DO UPDATE SET quantity = quantity + ?
        """,
        (player_id, case_id, qty, qty),
    )
    conn.commit()


def list_shop_cases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, description, price
        FROM cases
        ORDER BY id
        """
    )
    return cursor.fetchall()


def buy_case(conn: sqlite3.Connection, player_id: int, case_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute("SELECT id, price FROM cases WHERE name = ?", (case_name,))
    case_row = cursor.fetchone()
    if not case_row:
        return False
    cursor.execute("SELECT gold FROM players WHERE id = ?", (player_id,))
    player_row = cursor.fetchone()
    if not player_row or player_row["gold"] < case_row["price"]:
        return False
    cursor.execute(
        "UPDATE players SET gold = gold - ? WHERE id = ?",
        (case_row["price"], player_id),
    )
    cursor.execute(
        """
        INSERT INTO player_cases (player_id, case_id, quantity)
        VALUES (?, ?, 1)
        ON CONFLICT(player_id, case_id) DO UPDATE SET quantity = quantity + 1
        """,
        (player_id, case_row["id"]),
    )
    conn.commit()
    return True


def buy_case_by_id(conn: sqlite3.Connection, player_id: int, case_id: int) -> bool:
    cursor = conn.cursor()
    cursor.execute("SELECT price FROM cases WHERE id = ?", (case_id,))
    case_row = cursor.fetchone()
    if not case_row:
        return False
    cursor.execute("SELECT gold FROM players WHERE id = ?", (player_id,))
    player_row = cursor.fetchone()
    if not player_row or player_row["gold"] < case_row["price"]:
        return False
    cursor.execute(
        "UPDATE players SET gold = gold - ? WHERE id = ?",
        (case_row["price"], player_id),
    )
    cursor.execute(
        """
        INSERT INTO player_cases (player_id, case_id, quantity)
        VALUES (?, ?, 1)
        ON CONFLICT(player_id, case_id) DO UPDATE SET quantity = quantity + 1
        """,
        (player_id, case_id),
    )
    conn.commit()
    return True


def open_case(conn: sqlite3.Connection, player_id: int, case_name: str) -> list[Skill] | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.*, pc.quantity
        FROM cases c
        JOIN player_cases pc ON pc.case_id = c.id
        WHERE lower(c.name) = lower(?) AND pc.player_id = ?
        """,
        (case_name.strip(), player_id),
    )
    row = cursor.fetchone()
    if not row or row["quantity"] <= 0:
        return None
    cursor.execute(
        "UPDATE player_cases SET quantity = quantity - 1 WHERE player_id = ? AND case_id = ?",
        (player_id, row["id"]),
    )
    rewards = roll_case_rewards(conn, player_id, row)
    cursor.executemany(
        """
        INSERT OR IGNORE INTO player_skills (player_id, skill_id, is_unlocked)
        VALUES (?, ?, 1)
        """,
        [(player_id, skill.id) for skill in rewards],
    )
    conn.commit()
    return rewards
