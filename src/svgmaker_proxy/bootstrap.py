from __future__ import annotations

import logging
from dataclasses import dataclass

from svgmaker_proxy.clients.firebase_identity import FirebaseIdentityClient
from svgmaker_proxy.clients.svgmaker_generation import SvgmakerGenerationClient
from svgmaker_proxy.core.config import get_settings
from svgmaker_proxy.services.account_action_logger import AccountActionLogger
from svgmaker_proxy.services.account_pool import AccountPoolService
from svgmaker_proxy.services.account_registrar import AccountRegistrarService
from svgmaker_proxy.services.generation_proxy import GenerationProxyService
from svgmaker_proxy.storage.account_action_repository import AccountActionRepository
from svgmaker_proxy.storage.account_repository import AccountRepository
from svgmaker_proxy.storage.db import Database
from svgmaker_proxy.storage.generation_repository import GenerationRepository
from svgmaker_proxy.storage.telegram_invite_code_repository import TelegramInviteCodeRepository
from svgmaker_proxy.storage.telegram_user_repository import TelegramUserRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ServiceContainer:
    database: Database
    account_repository: AccountRepository
    account_action_repository: AccountActionRepository
    account_action_logger: AccountActionLogger
    generation_repository: GenerationRepository
    telegram_user_repository: TelegramUserRepository
    telegram_invite_code_repository: TelegramInviteCodeRepository
    account_registrar: AccountRegistrarService
    account_pool: AccountPoolService
    generation_proxy: GenerationProxyService


def build_services() -> ServiceContainer:
    settings = get_settings()
    database = Database(settings)
    account_repository = AccountRepository()
    account_action_repository = AccountActionRepository()
    account_action_logger = AccountActionLogger(account_action_repository)
    generation_repository = GenerationRepository()
    telegram_user_repository = TelegramUserRepository()
    telegram_invite_code_repository = TelegramInviteCodeRepository()
    firebase_client = FirebaseIdentityClient(settings)
    account_registrar = AccountRegistrarService(
        account_repository=account_repository,
        action_logger=account_action_logger,
        settings=settings,
        firebase_client=firebase_client,
    )
    account_pool = AccountPoolService(
        account_repository=account_repository,
        registrar=account_registrar,
        settings=settings,
    )
    generation_proxy = GenerationProxyService(
        account_pool=account_pool,
        account_repository=account_repository,
        generation_repository=generation_repository,
        generation_client=SvgmakerGenerationClient(settings),
        firebase_client=firebase_client,
        action_logger=account_action_logger,
        settings=settings,
    )
    return ServiceContainer(
        database=database,
        account_repository=account_repository,
        account_action_repository=account_action_repository,
        account_action_logger=account_action_logger,
        generation_repository=generation_repository,
        telegram_user_repository=telegram_user_repository,
        telegram_invite_code_repository=telegram_invite_code_repository,
        account_registrar=account_registrar,
        account_pool=account_pool,
        generation_proxy=generation_proxy,
    )


async def initialize_services(services: ServiceContainer) -> None:
    await services.database.initialize()
    gmail_profile = await services.account_registrar.gmail_service.healthcheck()
    logger.info(
        "Gmail healthcheck passed for %s (messages=%s)",
        gmail_profile["email_address"],
        gmail_profile.get("messages_total"),
    )
