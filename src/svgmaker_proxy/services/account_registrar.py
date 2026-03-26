from __future__ import annotations

import json
import logging
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from svgmaker_proxy.clients.firebase_identity import (
    FirebaseAuthTokens,
    FirebaseFirestoreUserDocument,
    FirebaseIdentityClient,
    FirebaseIdentityError,
    FirebaseLookupUser,
    FirebaseRefreshTokens,
)
from svgmaker_proxy.clients.svgmaker_auth import SvgmakerAuthClient, SvgmakerSession
from svgmaker_proxy.core.config import Settings, get_settings
from svgmaker_proxy.models.account import AccountCreate, AccountStatus, AccountUpdate
from svgmaker_proxy.models.account_action import AccountActionType
from svgmaker_proxy.services.account_action_logger import AccountActionLogger
from svgmaker_proxy.services.gmail_verification import GmailVerificationService
from svgmaker_proxy.storage.account_repository import AccountRepository

logger = logging.getLogger(__name__)

FIRST_NAMES = (
    "Alex",
    "Anna",
    "Ben",
    "Chloe",
    "Daniel",
    "Emma",
    "Ethan",
    "Grace",
    "Hannah",
    "Isaac",
    "Jack",
    "Julia",
    "Leo",
    "Liam",
    "Lucas",
    "Maya",
    "Mia",
    "Nathan",
    "Nora",
    "Olivia",
    "Owen",
    "Ryan",
    "Sofia",
    "Sophie",
    "Thomas",
    "Zoe",
)

LAST_NAMES = (
    "Adams",
    "Baker",
    "Bennett",
    "Brooks",
    "Carter",
    "Clark",
    "Coleman",
    "Cooper",
    "Davis",
    "Edwards",
    "Foster",
    "Garcia",
    "Gray",
    "Hall",
    "Hayes",
    "Hill",
    "Howard",
    "Hughes",
    "James",
    "Kelly",
    "Lewis",
    "Miller",
    "Morgan",
    "Parker",
    "Price",
    "Reed",
    "Ross",
    "Scott",
    "Taylor",
    "Turner",
    "Walker",
    "Ward",
    "White",
    "Young",
)


@dataclass(slots=True)
class RegisteredAccountBundle:
    account_id: int
    email: str
    password: str
    display_name: str
    firebase_local_id: str
    firebase_id_token: str
    firebase_refresh_token: str
    svgmaker_auth_token_id: str
    svgmaker_auth_token_refresh: str
    svgmaker_auth_token_sig: str
    email_verified: bool
    credits_last_known: int | None = None


class AccountRegistrarService:
    def __init__(
        self,
        account_repository: AccountRepository,
        settings: Settings | None = None,
        firebase_client: FirebaseIdentityClient | None = None,
        svgmaker_client: SvgmakerAuthClient | None = None,
        gmail_service: GmailVerificationService | None = None,
        action_logger: AccountActionLogger | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.account_repository = account_repository
        self.firebase_client = firebase_client or FirebaseIdentityClient(self.settings)
        self.svgmaker_client = svgmaker_client or SvgmakerAuthClient(self.settings)
        self.gmail_service = gmail_service or GmailVerificationService(self.settings)
        self.action_logger = action_logger

    async def register_account(self, email: str | None = None) -> RegisteredAccountBundle:
        if email:
            selected_email = email
            display_name = self._build_display_name(selected_email)
        else:
            selected_email, display_name = self._generate_identity()
        password = self._generate_password()

        account = await self.account_repository.create(
            AccountCreate(
                email=selected_email,
                password=password,
                display_name=display_name,
                status=AccountStatus.pending,
            )
        )
        logger.info("Created pending account record for %s", selected_email)
        await self._log_action(
            account.id,
            AccountActionType.account_created,
            email=selected_email,
            display_name=display_name,
        )

        signup_tokens: FirebaseAuthTokens | None = None
        refreshed_tokens: FirebaseRefreshTokens | None = None
        verified_session: SvgmakerSession | None = None

        try:
            logger.info("Starting Firebase signup for %s", selected_email)
            signup_tokens = await self.firebase_client.sign_up(
                email=selected_email,
                password=password,
            )
            logger.info(
                "Firebase signup succeeded email=%s local_id=%s email_verified=%s",
                selected_email,
                signup_tokens.local_id,
                False,
            )
            await self._log_action(
                account.id,
                AccountActionType.firebase_signup_succeeded,
                email=selected_email,
                firebase_local_id=signup_tokens.local_id,
            )
            await self.account_repository.update(
                account.id,
                AccountUpdate(
                    firebase_local_id=signup_tokens.local_id,
                    firebase_id_token=signup_tokens.id_token,
                    firebase_refresh_token=signup_tokens.refresh_token,
                ),
            )

            await self.firebase_client.update_display_name(
                signup_tokens.id_token,
                display_name,
            )
            logger.info("Updated displayName for %s -> %s", selected_email, display_name)
            await self._log_action(
                account.id,
                AccountActionType.display_name_updated,
                display_name=display_name,
            )
            await self.account_repository.update(
                account.id,
                AccountUpdate(display_name=display_name),
            )

            session = await self.svgmaker_client.login(signup_tokens.id_token)
            logger.info("Initial SVGMaker login succeeded for %s", selected_email)
            await self._log_action(account.id, AccountActionType.initial_login_succeeded)
            await self.account_repository.update(
                account.id,
                AccountUpdate(
                    svgmaker_auth_token_id=session.auth_token_id,
                    svgmaker_auth_token_refresh=session.auth_token_refresh,
                    svgmaker_auth_token_sig=session.auth_token_sig,
                ),
            )

            await self.account_repository.update(
                account.id,
                AccountUpdate(status=AccountStatus.verifying_email),
            )

            verification_link = await self._request_and_wait_for_verification_link(
                account_id=account.id,
                email=selected_email,
                id_token=signup_tokens.id_token,
            )
            if not verification_link:
                raise RuntimeError(f"Verification email was not received for {selected_email}")

            logger.info(
                "Verification email received for %s link=%s",
                selected_email,
                verification_link,
            )
            await self._log_action(
                account.id,
                AccountActionType.verification_email_received,
                verification_link=verification_link,
            )
            oob_code = self._extract_oob_code(verification_link)
            await self._confirm_email_verification(oob_code)
            logger.info("Email verification confirmed for %s", selected_email)
            await self._log_action(account.id, AccountActionType.email_verified)

            refreshed_tokens = await self.firebase_client.refresh(signup_tokens.refresh_token)
            logger.info("Firebase refresh succeeded for %s", selected_email)
            await self._log_action(account.id, AccountActionType.firebase_refresh_succeeded)
            lookup_users = await self.firebase_client.lookup(refreshed_tokens.id_token)
            lookup_user = self._resolve_lookup_user(lookup_users, selected_email)
            logger.info(
                "Firebase lookup after verification email=%s verified=%s display_name=%s",
                selected_email,
                lookup_user.email_verified,
                lookup_user.display_name,
            )
            if not lookup_user.email_verified:
                raise RuntimeError(f"Email is still not verified for {selected_email}")

            verified_session = await self.svgmaker_client.login(refreshed_tokens.id_token)
            logger.info("Verified SVGMaker login succeeded for %s", selected_email)
            await self._log_action(account.id, AccountActionType.verified_login_succeeded)
            await self.svgmaker_client.user_init(
                session=verified_session,
                firebase_local_id=signup_tokens.local_id,
                display_name=display_name,
            )
            logger.info("user_init succeeded for %s", selected_email)
            await self._log_action(account.id, AccountActionType.user_init_succeeded)
            daily_credits_payload = await self.svgmaker_client.check_daily_credits(verified_session)
            logger.info(
                "check_daily_credits for %s payload=%s",
                selected_email,
                self._compact_json(daily_credits_payload),
            )
            credit_facts = self._extract_credit_facts(daily_credits_payload)
            credits = self._extract_known_credits(daily_credits_payload)
            await self._log_action(
                account.id,
                AccountActionType.credits_checked,
                credits=credits,
                facts=credit_facts,
                raw_payload=daily_credits_payload,
                balance_known=credits is not None,
            )
            await self.svgmaker_client.post_signup_survey(verified_session)
            logger.info("post_signup_survey succeeded for %s", selected_email)
            await self._log_action(
                account.id,
                AccountActionType.post_signup_survey_completed,
                expected_credit_delta=10,
            )
            await self.svgmaker_client.complete_tour(verified_session)
            logger.info("complete_tour succeeded for %s", selected_email)
            await self._log_action(
                account.id,
                AccountActionType.tour_completed,
                tour="inputArea",
            )
            await self.svgmaker_client.update_preferences(verified_session)
            logger.info("update_preferences succeeded for %s", selected_email)
            await self._log_action(
                account.id,
                AccountActionType.preferences_updated,
                mode="generate",
            )
            firestore_user = await self._fetch_firestore_user_document(
                id_token=refreshed_tokens.id_token,
                firebase_local_id=signup_tokens.local_id,
                account_id=account.id,
                email=selected_email,
            )
            credits = self._resolve_best_known_credits(
                firestore_fields=firestore_user.fields,
                fallback_payload=daily_credits_payload,
            )
            credit_facts = self._merge_credit_facts(
                daily_credits_payload,
                firestore_user.fields,
            )
            logger.info(
                "Resolved credits for %s -> credits=%s facts=%s",
                selected_email,
                credits,
                self._compact_json(credit_facts),
            )
            update_payload = AccountUpdate(
                status=AccountStatus.active,
                email_verified=True,
                firebase_id_token=refreshed_tokens.id_token,
                firebase_refresh_token=refreshed_tokens.refresh_token,
                svgmaker_auth_token_id=verified_session.auth_token_id,
                svgmaker_auth_token_refresh=verified_session.auth_token_refresh,
                svgmaker_auth_token_sig=verified_session.auth_token_sig,
                last_refreshed_at=self._utcnow(),
                last_checked_at=self._utcnow(),
                failure_count=0,
            )
            if credits is not None:
                update_payload.credits_last_known = credits
            await self.account_repository.update(
                account.id,
                update_payload,
            )

            logger.info("Registered and verified account %s", selected_email)
            await self._log_action(
                account.id,
                AccountActionType.account_activated,
                credits=credits,
            )
            return RegisteredAccountBundle(
                account_id=account.id,
                email=selected_email,
                password=password,
                display_name=display_name,
                firebase_local_id=signup_tokens.local_id,
                firebase_id_token=refreshed_tokens.id_token,
                firebase_refresh_token=refreshed_tokens.refresh_token,
                svgmaker_auth_token_id=verified_session.auth_token_id,
                svgmaker_auth_token_refresh=verified_session.auth_token_refresh,
                svgmaker_auth_token_sig=verified_session.auth_token_sig,
                email_verified=True,
                credits_last_known=credits,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Account registration failed for %s", selected_email)
            await self.account_repository.update(
                account.id,
                AccountUpdate(
                    status=AccountStatus.failed,
                    failure_count=account.failure_count + 1,
                ),
            )
            raise RuntimeError(f"Account registration failed for {selected_email}: {exc}") from exc

    async def refresh_account_session(self, account_id: int) -> RegisteredAccountBundle:
        account = await self.account_repository.get_by_id(account_id)
        if not account:
            raise RuntimeError(f"Account {account_id} was not found")
        if not account.firebase_refresh_token:
            raise RuntimeError(f"Account {account_id} does not have a Firebase refresh token")

        refreshed = await self.firebase_client.refresh(account.firebase_refresh_token)
        lookup_users = await self.firebase_client.lookup(refreshed.id_token)
        lookup_user = self._resolve_lookup_user(lookup_users, account.email)
        session = await self.svgmaker_client.login(refreshed.id_token)
        credits_payload = await self.svgmaker_client.check_daily_credits(session)
        logger.info(
            "Refreshed account session credits account_id=%s email=%s payload=%s",
            account.id,
            account.email,
            self._compact_json(credits_payload),
        )
        credit_facts = self._extract_credit_facts(credits_payload)
        credits = self._extract_known_credits(credits_payload)
        firestore_user = await self._fetch_firestore_user_document(
            id_token=refreshed.id_token,
            firebase_local_id=account.firebase_local_id or refreshed.user_id,
            account_id=account.id,
            email=account.email,
        )
        credits = self._resolve_best_known_credits(
            firestore_fields=firestore_user.fields,
            fallback_payload=credits_payload,
        )
        credit_facts = self._merge_credit_facts(
            credits_payload,
            firestore_user.fields,
        )
        logger.info(
            "Resolved refreshed credits account_id=%s email=%s credits=%s facts=%s",
            account.id,
            account.email,
            credits,
            self._compact_json(credit_facts),
        )
        await self._log_action(
            account.id,
            AccountActionType.account_refresh_succeeded,
            credits=credits,
            facts=credit_facts,
            email_verified=lookup_user.email_verified,
            raw_payload=credits_payload,
            balance_known=credits is not None,
        )

        status = (
            AccountStatus.active
            if lookup_user.email_verified
            else AccountStatus.verifying_email
        )
        update_payload = AccountUpdate(
            status=status,
            email_verified=lookup_user.email_verified,
            firebase_id_token=refreshed.id_token,
            firebase_refresh_token=refreshed.refresh_token,
            svgmaker_auth_token_id=session.auth_token_id,
            svgmaker_auth_token_refresh=session.auth_token_refresh,
            svgmaker_auth_token_sig=session.auth_token_sig,
            last_refreshed_at=self._utcnow(),
            last_checked_at=self._utcnow(),
            failure_count=0,
        )
        if credits is not None:
            update_payload.credits_last_known = credits
        updated = await self.account_repository.update(
            account.id,
            update_payload,
        )
        if not updated:
            raise RuntimeError(f"Failed to persist refreshed account {account_id}")

        return RegisteredAccountBundle(
            account_id=updated.id,
            email=updated.email,
            password=updated.password,
            display_name=updated.display_name,
            firebase_local_id=updated.firebase_local_id or refreshed.user_id,
            firebase_id_token=refreshed.id_token,
            firebase_refresh_token=refreshed.refresh_token,
            svgmaker_auth_token_id=session.auth_token_id,
            svgmaker_auth_token_refresh=session.auth_token_refresh,
            svgmaker_auth_token_sig=session.auth_token_sig,
            email_verified=lookup_user.email_verified,
            credits_last_known=credits,
        )

    def _generate_identity(self) -> tuple[str, str]:
        domains = self.settings.email_domains_list
        if not domains:
            raise RuntimeError("EMAIL_DOMAINS must contain at least one domain")
        first_name, last_name = self._generate_person_name()
        patterns = (
            f"{first_name.lower()}.{last_name.lower()}",
            f"{first_name.lower()}{last_name.lower()}",
            f"{first_name.lower()}_{last_name.lower()}",
            f"{first_name.lower()}{last_name[0].lower()}",
            f"{first_name[0].lower()}{last_name.lower()}",
        )
        local = secrets.choice(patterns)
        suffix = secrets.randbelow(900) + 100
        if secrets.randbelow(100) < 70:
            local = f"{local}{suffix}"
        domain = domains[secrets.randbelow(len(domains))]
        return f"{local}@{domain}", f"{first_name} {last_name}"

    def _generate_password(self, length: int = 18) -> str:
        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(length - 2))
        return f"{password}A+"

    def _build_display_name(self, email: str) -> str:
        local = email.split("@", 1)[0]
        sanitized = local.replace(".", " ").replace("_", " ").replace("-", " ")
        parts = [part for part in sanitized.split() if part and not part.isdigit()]
        if len(parts) >= 2:
            return " ".join(part.capitalize() for part in parts[:2])
        if len(parts) == 1 and len(parts[0]) > 1:
            return parts[0].capitalize()
        first_name, last_name = self._generate_person_name()
        return f"{first_name} {last_name}"

    def _generate_person_name(self) -> tuple[str, str]:
        return (
            secrets.choice(FIRST_NAMES),
            secrets.choice(LAST_NAMES),
        )

    def _extract_oob_code(self, verification_link: str) -> str:
        parsed = urlparse(verification_link)
        values = parse_qs(parsed.query).get("oobCode", [])
        if not values or not values[0]:
            raise RuntimeError("Could not extract oobCode from verification link")
        return values[0]

    def _resolve_lookup_user(
        self,
        users: list[FirebaseLookupUser],
        email: str,
    ) -> FirebaseLookupUser:
        for user in users:
            if user.email.lower() == email.lower():
                return user
        if not users:
            raise RuntimeError(f"Firebase lookup returned no users for {email}")
        return users[0]

    def _extract_known_credits(self, payload: dict[str, Any]) -> int | None:
        facts = self._extract_credit_facts(payload)
        for key in (
            "credits",
            "remainingCredits",
            "availableCredits",
            "currentCredits",
            "dailyCredits",
        ):
            value = facts.get(key)
            if isinstance(value, int):
                return value
        return None

    def _extract_credit_facts(self, payload: dict[str, Any]) -> dict[str, int]:
        target_keys = {
            "credits",
            "remainingCredits",
            "availableCredits",
            "currentCredits",
            "dailyCredits",
            "initialUserCredits",
            "dailyFreeUserCredits",
        }
        found: dict[str, int] = {}

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key in target_keys and isinstance(nested, int):
                        found.setdefault(key, nested)
                    walk(nested)
                return
            if isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)
        return found

    def _merge_credit_facts(self, *payloads: dict[str, Any]) -> dict[str, int]:
        merged: dict[str, int] = {}
        for payload in payloads:
            merged.update(self._extract_credit_facts(payload))
        return merged

    def _resolve_best_known_credits(
        self,
        *,
        firestore_fields: dict[str, Any],
        fallback_payload: dict[str, Any],
    ) -> int | None:
        firestore_credits = self._extract_known_credits(firestore_fields)
        if firestore_credits is not None:
            return firestore_credits
        return self._extract_known_credits(fallback_payload)

    async def _fetch_firestore_user_document(
        self,
        *,
        id_token: str,
        firebase_local_id: str,
        account_id: int,
        email: str,
    ) -> FirebaseFirestoreUserDocument:
        try:
            firestore_user = await self.firebase_client.get_user_document(
                id_token=id_token,
                firebase_local_id=firebase_local_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to fetch Firestore user document account_id=%s email=%s local_id=%s: %s",
                account_id,
                email,
                firebase_local_id,
                exc,
            )
            return FirebaseFirestoreUserDocument(
                path=f"users/{firebase_local_id}",
                fields={},
                raw={},
            )
        credit_facts = self._extract_credit_facts(firestore_user.fields)
        logger.info(
            "Fetched Firestore user document account_id=%s email=%s path=%s facts=%s",
            account_id,
            email,
            firestore_user.path,
            self._compact_json(credit_facts),
        )
        await self._log_action(
            account_id,
            AccountActionType.firestore_user_document_fetched,
            path=firestore_user.path,
            credits=self._extract_known_credits(firestore_user.fields),
            facts=credit_facts,
        )
        return firestore_user

    async def _confirm_email_verification(self, oob_code: str) -> None:
        try:
            await self.firebase_client.verify_email_oob_code(oob_code)
            return
        except FirebaseIdentityError as exc:
            if "INVALID_OOB_CODE" in str(exc):
                logger.info(
                    "Got INVALID_OOB_CODE during verify_email_oob_code; "
                    "continuing to lookup because code may already be consumed"
                )
                return
            raise

    async def _request_and_wait_for_verification_link(
        self,
        *,
        account_id: int,
        email: str,
        id_token: str,
    ) -> str | None:
        for attempt in range(1, self.settings.verification_email_max_attempts + 1):
            verification_requested_at = time.time()
            verify_email_payload = await self.firebase_client.send_verify_email(
                id_token,
                continue_url=f"{self.settings.svgmaker_base_url}/auth/action",
            )
            logger.info(
                "Verification email requested for %s attempt=%s/%s payload=%s",
                email,
                attempt,
                self.settings.verification_email_max_attempts,
                self._compact_json(verify_email_payload),
            )
            await self._log_action(
                account_id,
                AccountActionType.verification_email_requested,
                payload=verify_email_payload,
                attempt=attempt,
                max_attempts=self.settings.verification_email_max_attempts,
            )

            verification_link = await self.gmail_service.wait_for_verification_link(
                to_email=email,
                since_ts=verification_requested_at,
                timeout=self.settings.verification_email_attempt_timeout_seconds,
                poll_interval=self.settings.email_poll_interval_seconds,
                lookback_seconds=20.0,
            )
            if verification_link:
                return verification_link

            if attempt < self.settings.verification_email_max_attempts:
                logger.warning(
                    "Verification email not received for %s after %.0fs on attempt %s/%s; retrying",
                    email,
                    self.settings.verification_email_attempt_timeout_seconds,
                    attempt,
                    self.settings.verification_email_max_attempts,
                )

        logger.warning(
            "Verification email was not received for %s after %s attempts",
            email,
            self.settings.verification_email_max_attempts,
        )
        return None

    def _utcnow(self):
        from datetime import UTC, datetime

        return datetime.now(UTC)

    def _compact_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    async def _log_action(
        self,
        account_id: int,
        action_type: AccountActionType,
        **details: Any,
    ) -> None:
        if self.action_logger is None:
            return
        await self.action_logger.log(account_id, action_type, **details)
