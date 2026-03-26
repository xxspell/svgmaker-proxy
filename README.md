# svgmaker-proxy

Async Python service for `svgmaker.io` with the following flow:

- Firebase/SVGMaker account registration
- email verification through Gmail forwarding
- PostgreSQL-backed account pool storage
- PostgreSQL-backed account action history
- round-robin account selection for generation
- automatic pool refill when the ready count drops below the configured threshold
- FastAPI API for pool management and generation proxying

## Implemented

- `FirebaseIdentityClient` for `accounts:signUp`, `accounts:lookup`, `accounts:update`, token refresh, and Firestore user document reads
- `SvgmakerAuthClient` for `/api/auth/login`, `/api/user-init`, `/api/check-daily-credits`, `/api/survey/post-signup`, `/api/user/tour-completed`, `/api/user/preferences`
- `SvgmakerGenerationClient` for `/api/generate` and SSE consumption
- `GmailVerificationService` built on `aiogoogle`
- `AccountRegistrarService` for registration, email verification, and post-signup flow
- `AccountPoolService` for round-robin leasing, refill, and account status updates
- `GenerationProxyService` for generation through pooled accounts
- direct Telegram bot integration that calls core services in-process instead of going through HTTP
- `AccountActionRepository` and action logging for account-level audit history
- FastAPI endpoints for registration, refill, account inspection, and generation proxying

The service considers an account usable only when:

- `status=active`
- `email_verified=true`
- all `AuthToken.*` SVGMaker cookies are present

## Registration Flow

The observed registration flow looks like this:

1. `POST https://identitytoolkit.googleapis.com/v1/accounts:signUp`
2. `POST https://identitytoolkit.googleapis.com/v1/accounts:update` for `displayName`
3. `POST https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode` with `requestType=VERIFY_EMAIL`
4. `POST https://svgmaker.io/api/auth/login`
5. wait for the email containing the verification link / `oobCode`
6. confirm email through Firebase `accounts:update` with `oobCode`
7. if Firebase returns `INVALID_OOB_CODE`, continue with `accounts:lookup` because the code may already have been consumed successfully
8. refresh the token and run `accounts:lookup` again
9. run `POST /api/auth/login` again
10. `POST /api/user-init`
11. `POST /api/check-daily-credits`
12. read the Firestore document `users/{firebase_local_id}` to get the exact `credits`
13. `POST /api/survey/post-signup`
14. `POST /api/user/tour-completed`
15. `POST /api/user/preferences`

Important details:

- `POST /api/check-daily-credits` does not always return a numeric balance
- the `svgmaker.io` frontend keeps the exact balance in the Firestore user document
- the service uses Firestore `users/{firebase_local_id}` as the primary source for `credits_last_known`
- verify email waiting uses retries by default: up to `3` send attempts with `100` seconds of waiting per attempt

## Generation Proxy Flow

1. acquire a ready account from the pool through round-robin
2. verify that the account has a complete `AuthToken.*` session
3. send `POST /api/generate`
4. if `402 Payment Required` is returned, retry the generation with another account
5. read the SSE stream until `complete`
6. persist the generation request in PostgreSQL
7. update account status:
   `failure_count=0` on success
   `cooling_down`, `blocked`, or `failed` on failure
8. capture Firestore balance snapshots before and after generation

## API

- `GET /health` - application status and pool snapshot
- `GET /metrics/summary` - short summary of the pool and recent generations
- `GET /accounts` - account list without secrets, including `ready` and `has_complete_session`
- `GET /accounts/ready` - only actually usable accounts
- `GET /accounts/{account_id}/actions` - action history for a single account
- `POST /accounts/register` - register an account manually
- `POST /accounts/refill` - refill the pool to the target size manually
- `POST /generate` - generation proxy
- `POST /proxy/generate` - alias for the generation proxy
- `GET /generations/{request_id}` - inspect a persisted generation record

## Telegram Bot

The repository now also contains a Telegram bot that uses the same core services directly:

- it does not call the local HTTP API
- it uses the same `GenerationProxyService` and account pool in-process
- it uses inline buttons for the main user flow

Current bot rules:

- a new user starts with `3` free generations
- free generations do not accumulate
- when the balance reaches `0`, the user receives `1` new generation on the next day
- if the user still has any remaining generations, no daily refill is granted
- a valid invite code can unlock unlimited generation access

Available bot entrypoints:

```bash
uv run svgmaker-proxy-stack
uv run svgmaker-proxy-telegram-bot
uv run svgmaker-proxy-create-invite --description "VIP unlimited access"
```

The invite command prints a deep-link payload that can be used with:

```text
https://t.me/<your_bot_username>?start=<invite_code>
```

Example generation request:

```bash
curl -X POST http://127.0.0.1:8000/proxy/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "minimal flat orange fox head logo, clean vector, white background",
    "quality": "high",
    "aspect_ratio": "auto",
    "background": "auto",
    "stream": true,
    "base64_png": false,
    "svg_text": true,
    "style_params": {}
  }'
```

Example response shape:

```json
{
  "request_id": 21,
  "account_id": 14,
  "generation_id": "abc123",
  "svg_url": "https://example.com/file.svg",
  "balance_before": 6,
  "balance_after": 3,
  "raw_payload": {}
}
```

## Configuration

See [`.env.example`](/Users/xxspell/Code/svgmaker-proxy/.env.example).

Key variables:

```env
SVGM_PROXY_HOST=0.0.0.0
SVGM_PROXY_PORT=8000
APP_ENV=dev
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5432/svgmaker_proxy

SVGM_BASE_URL=https://svgmaker.io
FIREBASE_API_KEY=
FIREBASE_PROJECT_ID=svgmaker-fun
FIREBASE_GMPID=
FIREBASE_CLIENT_VERSION=Chrome/JsCore/12.9.0/FirebaseCore-web

SVGM_PROXY_MIN_READY_ACCOUNTS=3
SVGM_PROXY_TARGET_READY_ACCOUNTS=5
SVGM_PROXY_MAX_CONCURRENT_REGISTRATIONS=2
SVGM_PROXY_MAX_ACCOUNTS_TOTAL=50
SVGM_PROXY_ACCOUNT_ERROR_LIMIT=3
SVGM_PROXY_ACCOUNT_SELECTION_STRATEGY=round_robin
SVGM_PROXY_POOL_REFILL_INTERVAL_SECONDS=60
SVGM_PROXY_GENERATION_RETRY_ATTEMPTS=3

SVGM_PROXY_REQUEST_TIMEOUT=60
SVGM_PROXY_GENERATE_TIMEOUT=300
SVGM_PROXY_EMAIL_DOMAINS=example.com,example.org,example.net
SVGM_PROXY_EMAIL_TIMEOUT_SECONDS=180
SVGM_PROXY_EMAIL_POLL_INTERVAL_SECONDS=5
SVGM_PROXY_VERIFY_EMAIL_ATTEMPT_TIMEOUT_SECONDS=100
SVGM_PROXY_VERIFY_EMAIL_MAX_ATTEMPTS=3

GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REFRESH_TOKEN=
GMAIL_ACCESS_TOKEN=

TELEGRAM_BOT_TOKEN=
TELEGRAM_INITIAL_GENERATIONS=3
TELEGRAM_DAILY_GENERATIONS=1
```

## Setup And Run

Install dependencies:

```bash
uv sync
```

Apply migrations:

```bash
uv run alembic upgrade head
```

After migration, the `account_actions` table stores key lifecycle events such as:

- account creation
- signup / verify / login / refresh
- `check_daily_credits`
- Firestore balance fetches
- `post_signup_survey`, `tour_completed`, `preferences_updated`
- generation start and completion

Run the API:

```bash
uv run uvicorn svgmaker_proxy.api.app:app --host 0.0.0.0 --port 8000
```

Run the Telegram bot:

```bash
uv run svgmaker-proxy-telegram-bot
```

Run API, Telegram bot, and background pool refill in one process:

```bash
uv run svgmaker-proxy-stack
```

## Validation

Check the main Python modules:

```bash
uv run ruff check src/svgmaker_proxy/api/app.py \
  src/svgmaker_proxy/core/config.py \
  src/svgmaker_proxy/models/account.py \
  src/svgmaker_proxy/services/account_pool.py \
  src/svgmaker_proxy/services/account_registrar.py \
  src/svgmaker_proxy/services/generation_proxy.py \
  src/svgmaker_proxy/services/gmail_verification.py
```

Full syntax check:

```bash
uv run python -m py_compile $(rg --files -g '*.py')
```
