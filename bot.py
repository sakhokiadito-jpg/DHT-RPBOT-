from __future__ import annotations

import asyncio
import logging
import sqlite3

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from config import Settings
from database import Database
from handlers.admin import build_admin_router
from handlers.catalog import build_catalog_router
from handlers.organizations import build_organization_router
from handlers.player import build_player_router
from middlewares.ban_guard import BanGuardMiddleware


async def run() -> None:
    settings = Settings()
    settings.validate()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is missing. Set it in the .env file.")

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = Database(settings.database_path)
    configured_admins = settings.admin_ids | settings.owner_ids
    database.initialize(configured_admins, settings.start_balance)

    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.message.middleware(
        BanGuardMiddleware(database, configured_admins)
    )
    dispatcher.include_routers(
        build_player_router(database, settings),
        build_catalog_router(database, settings),
        build_organization_router(database),
        build_admin_router(database, settings),
    )

    @dispatcher.errors()
    async def handle_update_error(event: ErrorEvent) -> bool:
        logger = logging.getLogger(__name__)
        error_info = (
            type(event.exception),
            event.exception,
            event.exception.__traceback__,
        )
        logger.error(
            "Update failed%s",
            " while accessing SQLite" if isinstance(event.exception, sqlite3.Error) else "",
            exc_info=error_info,
        )
        update = event.update
        message = update.message or update.edited_message
        if message:
            await message.answer("Не удалось обработать запрос. Попробуйте ещё раз позже.")
        elif update.callback_query:
            await update.callback_query.answer(
                "Не удалось выполнить действие. Попробуйте позже.",
                show_alert=True,
            )
        return True

    logging.getLogger(__name__).info(
        "DHT ROLEPLAY bot started; SQLite file: %s",
        settings.database_path,
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
