from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from svgmaker_proxy.api.app import (
    create_app,
    run_account_pool_refill_loop,
)
from svgmaker_proxy.bootstrap import build_services, initialize_services
from svgmaker_proxy.core.config import get_settings
from svgmaker_proxy.core.logging import configure_logging
from svgmaker_proxy.telegram.app import build_bot_service, configure_dispatcher
from svgmaker_proxy.telegram.session import build_bot_session

logger = logging.getLogger(__name__)


async def run_stack() -> None:
    settings = get_settings()

    configure_logging(settings.log_level)
    services = build_services()
    await initialize_services(services)

    app = create_app(services=services, manage_lifecycle=False)
    config = uvicorn.Config(
        app=app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)

    bot: Bot | None = None
    dispatcher: Dispatcher | None = None
    if settings.telegram_bot_token:
        bot = Bot(
            token=settings.telegram_bot_token,
            session=build_bot_session(settings.telegram_proxy_url),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dispatcher = Dispatcher()
        await configure_dispatcher(dispatcher, build_bot_service(services))
    else:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured; Telegram bot startup is skipped")

    tasks: list[asyncio.Task[object]] = [
        asyncio.create_task(server.serve(), name="svgmaker-api"),
        asyncio.create_task(run_account_pool_refill_loop(services), name="svgmaker-pool-refill"),
    ]
    if dispatcher is not None and bot is not None:
        tasks.append(asyncio.create_task(dispatcher.start_polling(bot), name="svgmaker-telegram"))

    async with app.state.mcp_server.session_manager.run():
        try:
            done, _ = await asyncio.wait(set(tasks), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
        finally:
            server.should_exit = True
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if bot is not None:
                await bot.session.close()
            await services.database.dispose()


def main() -> None:
    asyncio.run(run_stack())
