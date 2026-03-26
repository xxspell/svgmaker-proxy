from __future__ import annotations

import logging
from typing import Any

from svgmaker_proxy.models.account_action import AccountActionCreate, AccountActionType
from svgmaker_proxy.storage.account_action_repository import AccountActionRepository

logger = logging.getLogger(__name__)


class AccountActionLogger:
    def __init__(self, repository: AccountActionRepository) -> None:
        self.repository = repository

    async def log(
        self,
        account_id: int,
        action_type: AccountActionType,
        **details: Any,
    ) -> None:
        await self.repository.create(
            AccountActionCreate(
                account_id=account_id,
                action_type=action_type,
                details=details,
            )
        )
        logger.info(
            "Account action logged account_id=%s action=%s details=%s",
            account_id,
            action_type.value,
            details,
        )
