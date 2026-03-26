from __future__ import annotations

import asyncio
import base64
import html
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ClientCreds, UserCreds

from svgmaker_proxy.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class GmailVerificationService:
    OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
    LINK_RE = re.compile(r"""https://[^\s"'<>]+""")
    VERIFICATION_SUBJECT_RE = re.compile(r"verify your email for svgmaker", re.IGNORECASE)

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.gmail_client_id or not self.settings.gmail_client_secret:
            raise RuntimeError("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be configured")
        if not self.settings.gmail_refresh_token:
            raise RuntimeError("GMAIL_REFRESH_TOKEN must be configured")
        self.client_creds = ClientCreds(
            client_id=self.settings.gmail_client_id,
            client_secret=self.settings.gmail_client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
        )
        self.user_creds = UserCreds(
            access_token=self.settings.gmail_access_token or None,
            refresh_token=self.settings.gmail_refresh_token,
        )
        logger.critical(
            "gmail config: client_id=%s access_token=%s refresh_token=%s",
            self.settings.gmail_client_id,
            bool(self.settings.gmail_access_token),
            bool(self.settings.gmail_refresh_token),
        )

    async def _aiogoogle(self) -> Aiogoogle:
        return Aiogoogle(user_creds=self.user_creds, client_creds=self.client_creds)

    async def _discover_gmail(self, aig: Aiogoogle) -> Any:
        return await aig.discover("gmail", "v1")

    async def healthcheck(self) -> dict[str, Any]:
        try:
            async with await self._aiogoogle() as aig:
                gmail = await self._discover_gmail(aig)
                profile = await aig.as_user(gmail.users.getProfile(userId="me"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Gmail healthcheck failed: {exc}") from exc

        email_address = profile.get("emailAddress")
        if not email_address:
            raise RuntimeError("Gmail healthcheck failed: emailAddress missing in profile response")

        return {
            "email_address": email_address,
            "messages_total": profile.get("messagesTotal"),
            "threads_total": profile.get("threadsTotal"),
            "history_id": profile.get("historyId"),
        }

    async def _list_messages(self, aig: Aiogoogle, query: str) -> list[dict[str, Any]]:
        gmail = await self._discover_gmail(aig)
        result = await aig.as_user(
            gmail.users.messages.list(userId="me", q=query, includeSpamTrash=True)
        )
        return result.get("messages", [])

    async def _get_message(self, aig: Aiogoogle, msg_id: str) -> dict[str, Any]:
        gmail = await self._discover_gmail(aig)
        return await aig.as_user(
            gmail.users.messages.get(userId="me", id=msg_id, format="full")
        )

    async def _mark_read(self, aig: Aiogoogle, msg_id: str) -> None:
        gmail = await self._discover_gmail(aig)
        await aig.as_user(
            gmail.users.messages.modify(
                userId="me",
                id=msg_id,
                json={"removeLabelIds": ["UNREAD"]},
            )
        )

    async def _get_message_timestamp(self, aig: Aiogoogle, msg_id: str) -> float:
        gmail = await self._discover_gmail(aig)
        meta = await aig.as_user(
            gmail.users.messages.get(userId="me", id=msg_id, format="minimal")
        )
        return int(meta.get("internalDate", 0)) / 1000.0

    def _parse_part(self, part: dict[str, Any]) -> str:
        mime = part.get("mimeType", "")
        if mime in ("text/html", "text/plain"):
            data = part.get("body", {}).get("data", "")
            if data:
                padded = data + "=" * (-len(data) % 4)
                return base64.urlsafe_b64decode(padded).decode(
                    "utf-8", errors="replace"
                )
        for sub in part.get("parts", []):
            result = self._parse_part(sub)
            if result:
                return result
        return ""

    def _extract_body(self, message: dict[str, Any]) -> str:
        return html.unescape(self._parse_part(message.get("payload", {})))

    def _extract_headers(self, message: dict[str, Any]) -> dict[str, str]:
        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        return {item.get("name", "").lower(): item.get("value", "") for item in headers}

    def _find_verification_link(self, body: str) -> str | None:
        for match in self.LINK_RE.findall(body):
            candidate = html.unescape(match.rstrip(".,);"))
            if "mode=verifyEmail" in candidate or "oobCode=" in candidate:
                return candidate
        return None

    def _is_svgmaker_verification_message(
        self,
        headers: dict[str, str],
        body: str,
    ) -> bool:
        sender = headers.get("from", "").lower()
        subject = headers.get("subject", "")
        if "noreply@svgmaker.io" in sender and self.VERIFICATION_SUBJECT_RE.search(subject):
            return True

        verification_link = self._find_verification_link(body)
        if not verification_link:
            return False

        parsed = urlparse(verification_link)
        query = parse_qs(parsed.query)
        return (
            "svgmaker.io" in parsed.netloc.lower()
            and query.get("mode", [""])[0] == "verifyEmail"
            and bool(query.get("oobCode", [""])[0])
        )

    async def wait_for_verification_link(
        self,
        to_email: str,
        since_ts: float,
        timeout: float = 180.0,  # noqa: ASYNC109
        poll_interval: float = 5.0,
        lookback_seconds: float = 20.0,
    ) -> str | None:
        since_dt = datetime.fromtimestamp(since_ts).strftime("%Y/%m/%d")
        since_with_slack = since_ts - lookback_seconds
        query = (
            f'to:{to_email} '
            "("
            "from:noreply@svgmaker.io "
            "OR from:no-reply@accounts.google.com "
            "OR from:firebaseapp.com"
            ") "
            f'after:{since_dt}'
        )
        logger.info(
            "Waiting for verification email for %s since %s",
            to_email,
            datetime.fromtimestamp(since_with_slack).isoformat(timespec="seconds"),
        )

        deadline = time.time() + timeout
        checked: set[str] = set()

        while time.time() < deadline:
            try:
                async with await self._aiogoogle() as aig:
                    messages = await self._list_messages(aig, query)
                    for stub in messages:
                        msg_id = stub["id"]
                        if msg_id in checked:
                            continue

                        msg_ts = await self._get_message_timestamp(aig, msg_id)
                        if msg_ts < since_with_slack:
                            checked.add(msg_id)
                            continue

                        message = await self._get_message(aig, msg_id)
                        checked.add(msg_id)
                        body = self._extract_body(message)
                        headers = self._extract_headers(message)

                        subject = headers.get("subject", "")
                        if not body and not subject:
                            continue

                        if not self._is_svgmaker_verification_message(headers, body):
                            continue

                        verification_link = self._find_verification_link(body)
                        if verification_link:
                            await self._mark_read(aig, msg_id)
                            logger.info("Verification link found for %s", to_email)
                            return verification_link
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gmail poll error for %s: %s", to_email, exc)

            await asyncio.sleep(poll_interval)

        logger.warning("Timed out waiting for verification email for %s", to_email)
        return None

    async def wait_for_otp(
        self,
        to_email: str,
        since_ts: float,
        timeout: float = 120.0,  # noqa: ASYNC109
        poll_interval: float = 5.0,
    ) -> str | None:
        since_dt = datetime.fromtimestamp(since_ts).strftime("%Y/%m/%d")
        query = (
            f"to:{to_email} "
            f"(from:openai.com OR from:tm.openai.com OR from:noreply@tm.openai.com) "
            f"after:{since_dt}"
        )
        logger.info("Waiting for OTP for %s", to_email)

        deadline = time.time() + timeout
        checked: set[str] = set()

        while time.time() < deadline:
            try:
                async with await self._aiogoogle() as aig:
                    msgs = await self._list_messages(aig, query)
                    for stub in msgs:
                        msg_id = stub["id"]
                        if msg_id in checked:
                            continue

                        msg_ts = await self._get_message_timestamp(aig, msg_id)
                        if msg_ts < since_ts - 30:
                            checked.add(msg_id)
                            continue

                        message = await self._get_message(aig, msg_id)
                        checked.add(msg_id)
                        body = self._extract_body(message)
                        matched = self.OTP_RE.search(body)
                        if matched:
                            await self._mark_read(aig, msg_id)
                            return matched.group(1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gmail OTP poll error for %s: %s", to_email, exc)

            await asyncio.sleep(poll_interval)

        logger.warning("Timed out waiting for OTP for %s", to_email)
        return None
