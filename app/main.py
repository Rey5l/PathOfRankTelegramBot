import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import load_config
from app.db import init_db
from app.handlers import get_routers
from app import state


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    init_db(config.db_path)

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()
    for router in get_routers():
        dp.include_router(router)

    state.db_path = config.db_path
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
