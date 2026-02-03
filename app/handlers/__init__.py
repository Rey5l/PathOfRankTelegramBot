from aiogram import Router

from app.handlers.battle import router as battle_router
from app.handlers.cases import router as cases_router
from app.handlers.common import router as common_router
from app.handlers.duel import router as duel_router
from app.handlers.quest import router as quest_router
from app.handlers.shop import router as shop_router
from app.handlers.skills import router as skills_router


def get_routers() -> list[Router]:
    return [
        common_router,
        quest_router,
        shop_router,
        cases_router,
        skills_router,
        duel_router,
        battle_router,
    ]
