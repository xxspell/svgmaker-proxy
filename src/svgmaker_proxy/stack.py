from __future__ import annotations

import asyncio
import contextlib

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


async def run_stack() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured")

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

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    await configure_dispatcher(dispatcher, build_bot_service(services))

    api_task = asyncio.create_task(server.serve(), name="svgmaker-api")
    bot_task = asyncio.create_task(dispatcher.start_polling(bot), name="svgmaker-telegram")
    refill_task = asyncio.create_task(
        run_account_pool_refill_loop(services),
        name="svgmaker-pool-refill",
    )

    async with app.state.mcp_server.session_manager.run():
        try:
            done, _ = await asyncio.wait(
                {api_task, bot_task, refill_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
        finally:
            server.should_exit = True
            for task in (api_task, bot_task, refill_task):
                if not task.done():
                    task.cancel()
            for task in (api_task, bot_task, refill_task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await bot.session.close()
            await services.database.dispose()


def main() -> None:
    asyncio.run(run_stack())
