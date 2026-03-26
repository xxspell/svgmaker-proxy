from __future__ import annotations

import argparse
import asyncio

from svgmaker_proxy.bootstrap import build_services
from svgmaker_proxy.core.logging import configure_logging
from svgmaker_proxy.telegram.service import TelegramBotService


async def _run(description: str | None) -> None:
    services = build_services()
    await services.database.initialize()
    try:
        service = TelegramBotService(
            telegram_user_repository=services.telegram_user_repository,
            telegram_invite_code_repository=services.telegram_invite_code_repository,
            generation_proxy=services.generation_proxy,
        )
        invite = await service.create_invite_code(description=description)
        print(invite.code)
    finally:
        await services.database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Telegram unlimited invite code")
    parser.add_argument("--description", default=None, help="Optional description")
    args = parser.parse_args()
    configure_logging("INFO")
    asyncio.run(_run(args.description))


if __name__ == "__main__":
    main()
