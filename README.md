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
- `POST /edit` - edit proxy
- `POST /proxy/edit` - alias for the edit proxy
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

## MCP Server

The repository also contains a private MCP server intended for AI tools and IDE integrations.

Design goals:

- expose SVG generation and editing
- hide account rotation, retries, pool refill, and balance logic
- reuse the same local proxy services instead of the official SVGMaker API key flow

Current MCP tools:

- `svgmaker_generate`
- `svgmaker_generate_link`
- `svgmaker_edit`
- `svgmaker_edit_link`

`svgmaker_generate` accepts:

- `prompt`
- `quality`
- `aspect_ratio`
- `background`

It returns:

- `generation_id`
- `svg_url`
- `svg_text`

`svgmaker_generate_link` accepts:

- `prompt`
- `quality`
- `aspect_ratio`
- `background`

It returns only lightweight fields:

- `generation_id`
- `svg_url`

`svgmaker_edit` accepts:

- `prompt`
- `source_svg_text` or `source_file_text`
- optional `source_filename`
- `quality`
- `aspect_ratio`
- `background`

It returns:

- `generation_id`
- `svg_url`
- `svg_text`

`svgmaker_edit_link` accepts the same edit inputs and returns only:

- `generation_id`
- `svg_url`

Recommendation:

- use `svgmaker_generate_link` or `svgmaker_edit_link` for remote HTTP MCP clients
- use `svgmaker_generate` or `svgmaker_edit` when you need raw `svg_text`

For edit tools, provide exactly one source mode:

- `source_svg_text` for inline SVG markup
- `source_file_text` for uploaded-file style SVG content

The HTTP API exposes the same edit capability via JSON and multipart form requests.

JSON mode uses raw SVG text:

```bash
curl -X POST http://127.0.0.1:8000/proxy/edit \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "make the strokes thicker and change the fill to blue",
    "quality": "high",
    "aspect_ratio": "auto",
    "background": "auto",
    "stream": true,
    "svg_text": true,
    "source_svg_text": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 100 100\"><circle cx=\"50\" cy=\"50\" r=\"30\" fill=\"red\"/></svg>"
  }'
```

Multipart mode uses an uploaded SVG file:

```bash
curl -X POST http://127.0.0.1:8000/proxy/edit \
  -F 'prompt=make the icon monochrome black' \
  -F 'quality=high' \
  -F 'aspect_ratio=auto' \
  -F 'background=auto' \
  -F 'stream=true' \
  -F 'svg_text=true' \
  -F 'image=@./input.svg;type=image/svg+xml'
```

Edit responses follow the same proxy response shape as generation.

Example edit response shape:

```json
{
  "request_id": 22,
  "account_id": 14,
  "generation_id": "edit_abc123",
  "svg_url": "https://example.com/edited.svg",
  "balance_before": 3,
  "balance_after": 0,
  "raw_payload": {}
}
```

If upstream rejects invalid SVG input, the request fails without counting it as an account failure.

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

Example generation response shape:

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

Example edit request:

```bash
curl -X POST http://127.0.0.1:8000/proxy/edit \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "turn this into a green outline icon",
    "quality": "high",
    "aspect_ratio": "auto",
    "background": "auto",
    "stream": true,
    "svg_text": true,
    "source_svg_text": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path d=\"M4 4h16v16H4z\" fill=\"#f00\"/></svg>"
  }'
```

Example edit response shape:

```json
{
  "request_id": 22,
  "account_id": 14,
  "generation_id": "edit_abc123",
  "svg_url": "https://example.com/edited.svg",
  "balance_before": 3,
  "balance_after": 0,
  "raw_payload": {}
}
```

Recommendation still applies:

- use link-style tools and endpoints when you only need the resulting URL
- use the full variants when you need raw `svg_text`

The edit flow reuses the same pooled-account proxy behavior as generation, including retry on `402 Payment Required`.

Current HTTP examples:

Generation request:

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

Generation response shape:

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

Edit request (JSON raw SVG text):

```bash
curl -X POST http://127.0.0.1:8000/proxy/edit \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "make the icon monochrome black",
    "quality": "high",
    "aspect_ratio": "auto",
    "background": "auto",
    "stream": true,
    "svg_text": true,
    "source_svg_text": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\"><path d=\"M4 4h16v16H4z\" fill=\"#f00\"/></svg>"
  }'
```

Edit request (multipart upload):

```bash
curl -X POST http://127.0.0.1:8000/proxy/edit \
  -F 'prompt=make the icon monochrome black' \
  -F 'quality=high' \
  -F 'aspect_ratio=auto' \
  -F 'background=auto' \
  -F 'stream=true' \
  -F 'svg_text=true' \
  -F 'image=@./input.svg;type=image/svg+xml'
```

Edit response shape:

```json
{
  "request_id": 22,
  "account_id": 14,
  "generation_id": "edit_abc123",
  "svg_url": "https://example.com/edited.svg",
  "balance_before": 3,
  "balance_after": 0,
  "raw_payload": {}
}
```

Invalid SVG edit input is treated as a request failure, not as an account health failure.

The rest of the runtime and deployment setup stays the same.

Current MCP generation and edit tools can all be served over stdio or mounted HTTP MCP.

Use the same stdio and HTTP MCP configurations below.

Existing server entrypoints remain unchanged.

Current HTTP and MCP examples continue below.

Current response envelope for proxy endpoints remains shared across generation and edit.

The examples below use `/proxy/generate`, but `/generate` and `/edit` aliases are also available.

The generation example remains available for compatibility reference.

The edit examples are the preferred reference when integrating SVG modification support.

Use the file-upload edit path when you already have an `.svg` file on disk.

Use the raw-text edit path when an agent or client already has the SVG markup in memory.

The proxy still hides account leasing and balance bookkeeping from callers.

All edit requests persist their own records separately from generation requests.

The account pool logic is shared between generation and edit.

The upstream `/api/edit` SSE stream is consumed to completion before returning the final payload.

The final result contract remains intentionally generation-like for easier client reuse.

The remaining sections below cover runtime configuration and deployment.

Run the MCP server over stdio:

```bash
uv run svgmaker-proxy-mcp
```

For server deployments, the FastAPI app also mounts the MCP endpoint over HTTP at:

```text
/mcp
```

That means when your API is running on `https://your-domain.example`, the MCP endpoint is:

```text
https://your-domain.example/mcp
```

Example local stdio MCP client configuration:

```json
{
  "mcpServers": {
    "svgmaker-proxy": {
      "command": "uv",
      "args": ["run", "svgmaker-proxy-mcp"],
      "transport": "stdio"
    }
  }
}
```

Example remote HTTP MCP client configuration:

```json
{
  "mcpServers": {
    "svgmaker-proxy": {
      "transport": "streamable-http",
      "url": "https://your-domain.example/mcp"
    }
  }
}
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

See [`.env.example`](./.env.example).

Key variables:

```env
POSTGRES_DB=svgmaker_proxy
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_PORT=5432

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
SVGM_PROXY_GENERATE_MIN_CREDITS=3
SVGM_PROXY_EDIT_MIN_CREDITS=5
SVGM_PROXY_ACCOUNT_ACQUIRE_WAIT_SECONDS=180
SVGM_PROXY_ACCOUNT_ACQUIRE_POLL_INTERVAL_SECONDS=2
SVGM_PROXY_UNKNOWN_BALANCE_REFRESH_INTERVAL_SECONDS=3600
SVGM_PROXY_LOW_BALANCE_REFRESH_INTERVAL_SECONDS=90000
SVGM_PROXY_KNOWN_BALANCE_REFRESH_INTERVAL_SECONDS=86400
SVGM_PROXY_MAX_BALANCE_REFRESH_PER_CYCLE=3
SVGM_PROXY_ZERO_BALANCE_REFRESH_INTERVAL_SECONDS=90000

SVGM_PROXY_REQUEST_TIMEOUT=60
SVGM_PROXY_GENERATE_TIMEOUT=300
# Stream mode for /api/generate and /api/edit calls.
# true  - use SSE stream mode (default)
# false - use regular JSON response mode (recommended with unstable proxies)
SVGM_STREAM_ENABLED=true
# HTTP_PROXY_URL examples:
# HTTP_PROXY_URL=http://host:port
# HTTP_PROXY_URL=http://user:pass@host:port
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
# TELEGRAM_PROXY_URL examples:
# TELEGRAM_PROXY_URL=http://host:port
# TELEGRAM_PROXY_URL=http://user:pass@host:port
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

## Docker Compose

The repository includes a containerized application service and an optional bundled PostgreSQL service.

The application container:

- runs migrations on startup with `uv run alembic upgrade head`
- starts the unified stack with `uv run svgmaker-proxy-stack`
- serves the HTTP API and mounted MCP endpoint from the same container
- runs the Telegram bot in the same container when `TELEGRAM_BOT_TOKEN` is configured
- includes Cairo and related native libraries needed for Telegram SVG to PNG conversion

Recommended mode: use your existing external PostgreSQL instance by setting `DATABASE_URL` in `.env` and starting only the app container:

```bash
docker compose up --build
```

Important: when running inside Docker, `DATABASE_URL` must point to a reachable network host for PostgreSQL, not `127.0.0.1` inside the container.
Use your LAN IP or DNS name for the external database host.
If `DATABASE_URL` is not provided, Compose falls back to the optional bundled profile URL `postgresql+asyncpg://postgres:postgres@postgres:5432/svgmaker_proxy`.

If you want the bundled PostgreSQL container instead, start the optional `local-db` profile and point `DATABASE_URL` at the `postgres` service:

```bash
docker compose --profile local-db up --build
```
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/svgmaker_proxy
```

If `TELEGRAM_BOT_TOKEN` is omitted, the container still starts API, MCP, and background refill; only Telegram bot polling is skipped.

The app service also exposes a Docker healthcheck via `/health`.
You can change `SVGM_PROXY_PORT` in `.env`, and Docker Compose will use the same port for the app listener, published port, and healthcheck.

Run in the background:

```bash
docker compose up --build -d
```

Stop the stack:

```bash
docker compose down
```

The API is exposed on:

```text
http://127.0.0.1:${SVGM_PROXY_PORT}
```

The HTTP MCP endpoint is exposed on:

```text
http://127.0.0.1:${SVGM_PROXY_PORT}/mcp
```

When using Docker Compose, the application container reads `DATABASE_URL` from `.env`.
The bundled `postgres` service is optional and is only started when the `local-db`
profile is enabled.

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
