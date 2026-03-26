from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from svgmaker_proxy.core.config import Settings, get_settings


class FirebaseIdentityError(RuntimeError):
    """Raised when Firebase Identity Toolkit returns an error response."""


@dataclass(slots=True)
class FirebaseAuthTokens:
    local_id: str
    email: str
    id_token: str
    refresh_token: str
    expires_in: int


@dataclass(slots=True)
class FirebaseLookupUser:
    local_id: str
    email: str
    email_verified: bool
    display_name: str | None = None
    custom_auth: bool | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class FirebaseRefreshTokens:
    access_token: str
    refresh_token: str
    id_token: str
    user_id: str
    project_id: str
    expires_in: int


@dataclass(slots=True)
class FirebaseFirestoreUserDocument:
    path: str
    fields: dict[str, Any]
    raw: dict[str, Any]


class FirebaseIdentityClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client

    async def sign_up(self, email: str, password: str) -> FirebaseAuthTokens:
        payload = {
            "returnSecureToken": True,
            "email": email,
            "password": password,
            "clientType": "CLIENT_TYPE_WEB",
        }
        data = await self._post_json("accounts:signUp", payload)
        return self._parse_auth_tokens(data)

    async def lookup(self, id_token: str) -> list[FirebaseLookupUser]:
        data = await self._post_json("accounts:lookup", {"idToken": id_token})
        users = data.get("users", [])
        return [self._parse_lookup_user(user) for user in users]

    async def update_display_name(
        self,
        id_token: str,
        display_name: str,
    ) -> dict[str, Any]:
        return await self._post_json(
            "accounts:update",
            {
                "idToken": id_token,
                "displayName": display_name,
                "returnSecureToken": True,
            },
        )

    async def send_verify_email(
        self,
        id_token: str,
        continue_url: str | None = None,
        *,
        can_handle_code_in_app: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "requestType": "VERIFY_EMAIL",
            "idToken": id_token,
            "canHandleCodeInApp": can_handle_code_in_app,
        }
        if continue_url:
            payload["continueUrl"] = continue_url
        return await self._post_json("accounts:sendOobCode", payload)

    async def verify_email_oob_code(self, oob_code: str) -> dict[str, Any]:
        return await self._post_json("accounts:update", {"oobCode": oob_code})

    async def refresh(self, refresh_token: str) -> FirebaseRefreshTokens:
        data = await self._post_form(
            "https://securetoken.googleapis.com/v1/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        return FirebaseRefreshTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            id_token=data["id_token"],
            user_id=data["user_id"],
            project_id=data["project_id"],
            expires_in=int(data["expires_in"]),
        )

    async def get_user_document(
        self,
        id_token: str,
        firebase_local_id: str,
    ) -> FirebaseFirestoreUserDocument:
        client = self._client()
        response = await client.get(
            self._firestore_user_url(firebase_local_id),
            headers=self._firestore_headers(id_token),
        )
        payload = self._handle_response(response)
        return FirebaseFirestoreUserDocument(
            path=payload["name"],
            fields=self._decode_firestore_fields(payload.get("fields", {})),
            raw=payload,
        )

    async def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._identity_url(endpoint)
        client = self._client()
        response = await client.post(url, json=payload, headers=self._firebase_headers())
        return self._handle_response(response)

    async def _post_form(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._client()
        response = await client.post(
            url,
            data=payload,
            params={"key": self.settings.firebase_api_key},
            headers=self._firebase_headers(content_type="application/x-www-form-urlencoded"),
        )
        return self._handle_response(response)

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)

    def _identity_url(self, endpoint: str) -> str:
        return f"https://identitytoolkit.googleapis.com/v1/{endpoint}?key={self.settings.firebase_api_key}"

    def _firestore_user_url(self, firebase_local_id: str) -> str:
        return (
            "https://firestore.googleapis.com/v1/projects/"
            f"{self.settings.firebase_project_id}/databases/(default)/documents/"
            f"users/{firebase_local_id}"
        )

    def _firebase_headers(self, content_type: str = "application/json") -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "*/*",
            "Origin": self.settings.svgmaker_origin,
            "Content-Type": content_type,
            "X-Client-Version": self.settings.firebase_client_version,
            "X-Firebase-gmpid": self.settings.firebase_gmpid,
            "X-Browser-Channel": "stable",
            "X-Browser-Year": "2026",
            "X-Browser-Validation": "Cts+hOkVcBHYzhzRaAiF3uEw6wk=",
            "X-Browser-Copyright": "Copyright 2026 Google LLC. All Rights reserved.",
            "Accept-Language": self.settings.accept_language,
        }

    def _firestore_headers(self, id_token: str) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "application/json",
            "Authorization": f"Bearer {id_token}",
            "x-goog-api-key": self.settings.firebase_api_key,
            "Accept-Language": self.settings.accept_language,
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FirebaseIdentityError(
                f"Unexpected Firebase response ({response.status_code}): {response.text}"
            ) from exc

        if response.is_success:
            return payload

        error = payload.get("error", {})
        message = error.get("message") or payload
        raise FirebaseIdentityError(f"Firebase request failed: {message}")

    def _parse_auth_tokens(self, payload: dict[str, Any]) -> FirebaseAuthTokens:
        return FirebaseAuthTokens(
            local_id=payload["localId"],
            email=payload["email"],
            id_token=payload["idToken"],
            refresh_token=payload["refreshToken"],
            expires_in=int(payload["expiresIn"]),
        )

    def _parse_lookup_user(self, payload: dict[str, Any]) -> FirebaseLookupUser:
        return FirebaseLookupUser(
            local_id=payload["localId"],
            email=payload["email"],
            email_verified=bool(payload.get("emailVerified", False)),
            display_name=payload.get("displayName"),
            custom_auth=payload.get("customAuth"),
            raw=payload,
        )

    def _decode_firestore_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._decode_firestore_value(value)
            for key, value in fields.items()
        }

    def _decode_firestore_value(self, value: dict[str, Any]) -> Any:
        if "nullValue" in value:
            return None
        if "booleanValue" in value:
            return value["booleanValue"]
        if "integerValue" in value:
            return int(value["integerValue"])
        if "doubleValue" in value:
            return float(value["doubleValue"])
        if "timestampValue" in value:
            return value["timestampValue"]
        if "stringValue" in value:
            return value["stringValue"]
        if "bytesValue" in value:
            return value["bytesValue"]
        if "referenceValue" in value:
            return value["referenceValue"]
        if "geoPointValue" in value:
            return value["geoPointValue"]
        if "arrayValue" in value:
            values = value["arrayValue"].get("values", [])
            return [self._decode_firestore_value(item) for item in values]
        if "mapValue" in value:
            return self._decode_firestore_fields(value["mapValue"].get("fields", {}))
        return value
