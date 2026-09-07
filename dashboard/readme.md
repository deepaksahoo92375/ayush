# Ayush AI Dashboard

The dashboard is intentionally kept in the same `ayush` repository but runs as a separate web service.

## Current architecture
- Bot: GitHub Actions rotation chain
- Telemetry: Gist (`ayush_stats.json`)
- Admin access: Telegram OIDC
- Public page: bot + community links only
- Private page: users, groups, activity, providers, tokens, errors and last-hour logs
- Owner: can add/remove numeric Telegram sudo IDs

## Environment
PUBLIC_BASE_URL=
TELEGRAM_CLIENT_ID=
TELEGRAM_CLIENT_SECRET=
OWNER_ID=
GIST_ID=
GIST_TOKEN=
BOT_TOKEN=
SESSION_SECRET=
COOKIE_SECURE=true

## Run locally
cd dashboard
pip install -r requirements.txt
uvicorn dashboard:app --host 0.0.0.0 --port 8000

Telegram OIDC login requires a public HTTPS callback registered for the bot. For a real admin-login test, use a public host/tunnel or deploy this dashboard to a web service.
