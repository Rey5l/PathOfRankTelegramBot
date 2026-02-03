from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str


def load_config() -> Config:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")
    db_path = os.getenv("DB_PATH", "rpg_bot.sqlite3")
    return Config(bot_token=bot_token, db_path=db_path)
