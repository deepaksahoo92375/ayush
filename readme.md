<div align="center">

<img src="assets/ayush-banner.svg" alt="Ayush AI Banner" width="100%"/>

# Ayush AI

### A production-oriented Telegram AI assistant with multi-provider fallback, telemetry, administration, and a protected web dashboard.

<p>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram"/>
  <img src="https://img.shields.io/badge/FastAPI-Dashboard-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/GitHub-Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white" alt="GitHub Actions"/>
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
</p>

<p>
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#deployment">Deployment</a> •
  <a href="#dashboard">Dashboard</a>
</p>

</div>

---

## ✨ Overview

**Ayush AI** is a Python-based Telegram assistant designed around a resilient AI-provider architecture rather than a single model endpoint.

The repository contains two connected services:

- **Telegram bot** — conversational AI, commands, safety/rate controls, memory, telemetry, and administrative tooling.
- **Web dashboard** — FastAPI application for public information, protected administration, activity/usage visibility, and owner/sudo access management.

The project also includes GitHub Actions workflows, Docker/Fly.io deployment configuration, health endpoints, and GitHub Gist-backed telemetry/access persistence.

> **Design goal:** keep the Telegram experience available when an individual AI provider fails by moving through the configured provider chain.

---

## 🚀 Highlights

| Area | Included |
|---|---|
| Telegram | Private/group conversations, commands, new-member welcome handling |
| AI | Gemini ×2, OpenAI, OpenRouter Free, Groq, Cerebras |
| Reliability | Ordered provider fallback and busy/failure handling |
| Conversation | Memory/session handling and reset command |
| Safety | Toxic-content detection and rate limiting |
| Input | Text plus photo/image handling |
| Output | Long-message splitting and technical/academic response formatting |
| Administration | Owner/sudo controls, sudo authentication, broadcast |
| Telemetry | Activity, provider usage, errors, logs and statistics |
| Persistence | GitHub Gist statistics/access data |
| Dashboard | FastAPI + Jinja web interface |
| Authentication | Telegram OIDC with session protection |
| Deployment | GitHub Actions, Docker, Procfile, Fly.io configuration |
| Public access | Tailscale Funnel support in dashboard workflow |
| Operations | Health, provider, activity, user, group and log APIs |

---

## 🧩 Features

### 🤖 Telegram AI Assistant

- AI-powered Telegram conversations.
- Works in group and private-chat contexts supported by the bot handlers.
- Language detection and regional-language response handling.
- Casual-response handling for lightweight interactions.
- Conversation memory with reset support.
- Technical/academic response mode.
- Mathematical response formatting designed for Telegram-friendly Unicode output.
- Image/photo processing path with OCR-oriented handling.
- Long responses are split before delivery to Telegram.

### 🔁 Multi-provider AI fallback

The current provider chain is:

```text
Gemini API 1
     ↓
Gemini API 2
     ↓
OpenAI
     ↓
OpenRouter Free
     ↓
Groq
     ↓
Cerebras
```

The exact provider/model availability depends on the environment variables configured for the deployment.

This architecture allows the bot to continue attempting the next configured provider after an upstream failure.

### 🛡️ Safety, limits & operational controls

The bot includes:

- User rate limiting.
- Toxic-content detection.
- Input sanitization.
- AI failure handling.
- Developer issue reporting.
- Busy/failure notice management.
- Daily developer reporting.
- Workflow/runtime warning support.

### 👑 Owner & sudo management

Administrative handlers include:

```text
/addsudoauth
/addsudo
/removesudo
/sudolist
/broadcast
```

The repository distinguishes owner and sudo access and supports dashboard-managed sudo access.

Sudo authentication records are handled as salted PBKDF2-derived password hashes rather than storing the plaintext password.

### 📊 Telemetry & statistics

The bot records operational information such as:

- User activity.
- Group activity.
- AI provider usage.
- Errors.
- Logs.
- Toxic-content events.
- Runtime statistics.

Statistics can be persisted through a GitHub Gist using:

```text
GIST_ID
GIST_TOKEN
GIST_FILENAME
```

### 🌐 FastAPI dashboard

The `dashboard/` service provides:

- Public landing page.
- Protected admin area.
- Telegram OIDC authentication.
- Owner/sudo authorization.
- Users view.
- Groups view.
- Activity information.
- Provider information.
- Logs.
- Access management.
- Wallpaper API.
- Dashboard API.
- Health endpoint.

The dashboard workflow also supports exposing the service through **Tailscale Funnel**.

---

# 🏗️ Architecture

<img src="assets/architecture.svg" alt="Ayush AI architecture" width="100%"/>

### Request flow

```text
Telegram user
     │
     ▼
Telegram Bot
     │
     ├── Language / mode detection
     ├── Rate limiting
     ├── Safety checks
     ├── Memory / session handling
     │
     ▼
AI fallback chain
     │
     ├── Gemini #1
     ├── Gemini #2
     ├── OpenAI
     ├── OpenRouter
     ├── Groq
     └── Cerebras
     │
     ▼
Telegram response
     │
     └── Telemetry / statistics
                 │
                 ▼
             GitHub Gist
                 │
                 ▼
          FastAPI dashboard
```

---

# 🖥️ Dashboard architecture

<img src="assets/security-flow.svg" alt="Ayush AI security and access flow" width="100%"/>

The dashboard is deliberately separated from the Telegram bot runtime.

```text
Browser
   │
   ▼
FastAPI
   │
   ├── Public routes
   │
   ├── Telegram OIDC
   │       │
   │       ▼
   │   Session
   │       │
   │       ▼
   │   Owner / Sudo authorization
   │
   └── Admin APIs
           │
           ▼
       GitHub Gist
```

---

# 📁 Project structure

```text
ayush-main/
│
├── bot.py
├── requirements.txt
├── Dockerfile
├── Procfile
├── fly.toml
├── runtime.txt
├── .gitignore
│
├── .github/
│   └── workflows/
│       ├── bot.yml
│       └── dashboard.yml
│
├── dashboard/
│   ├── dashboard.py
│   ├── requirements.txt
│   ├── readme.md
│   │
│   ├── static/
│   │   └── site.css
│   │
│   └── templates/
│       ├── index.html
│       └── admin.html
│
└── assets/
    ├── ayush-banner.svg
    ├── architecture.svg
    └── security-flow.svg
```

---

# ⚡ Quick Start

## 1. Clone the repository

```bash
git clone https://github.com/deepaksahoo92375/ayush.git
cd ayush
```

## 2. Create a virtual environment

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Configure environment variables

Create a `.env` file for local development or export the variables through your deployment platform.

At minimum, the bot requires:

```env
BOT_TOKEN=
DEVELOPER_GROUP_ID=
OWNER_ID=
```

Then add whichever AI providers you want enabled.

---

# 🔐 Configuration

## Core Telegram configuration

```env
BOT_TOKEN=
DEVELOPER_GROUP_ID=
OWNER_ID=
SUDO_USERS=
```

## AI providers

```env
GEMINI_API_KEY_1=
GEMINI_API_KEY_2=
OPENAI_API_KEY=
OPENROUTER_API_KEY=
GROQ_API_KEY=
CEREBRAS_API_KEY=
```

The workflows currently configure model environment values including:

```env
GEMINI_MODEL=gemini-3.5-flash-lite
OPENAI_MODEL=gpt-4o-mini
GROQ_MODEL=openai/gpt-oss-20b
OPENROUTER_MODEL=openrouter/free
CEREBRAS_MODEL=gpt-oss-120b
```

> Model IDs are deployment configuration, not hard-coded guarantees. Verify provider availability before production deployment.

## Telemetry / Gist

```env
GIST_ID=
GIST_TOKEN=
GIST_FILENAME=ayush_stats.json
```

## Runtime/report configuration

```env
DAILY_REPORT_HOUR=
DAILY_REPORT_MINUTE=
REPORT_TIMEZONE=
TASK_WARNING_MINUTES=
TASK_WARNING_AFTER_MINUTES=
```

## Bot health server

```env
FLASK_PORT=8080
```

---

# 🧪 Run the bot locally

After configuring the required environment variables:

```bash
python bot.py
```

For a quick syntax validation:

```bash
python -m py_compile bot.py
```

---

# 🌐 Run the dashboard locally

```bash
cd dashboard
pip install -r requirements.txt
uvicorn dashboard:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Telegram OIDC login requires a publicly reachable HTTPS callback when performing a real authentication test.

---

# 🔄 GitHub Actions deployment

The repository includes two workflows.

## Bot workflow

```text
.github/workflows/bot.yml
```

The workflow:

1. Checks out the repository.
2. Installs Python 3.11.
3. Installs dependencies.
4. Verifies `bot.py`.
5. Runs a Python syntax check.
6. Validates required secrets.
7. Starts the bot.

The current schedule is:

```yaml
cron: "0 */5 * * *"
```

The workflow uses a maximum runtime of approximately 5.5 hours per run and is configured with concurrency protection.

## Dashboard workflow

```text
.github/workflows/dashboard.yml
```

The dashboard workflow:

1. Checks out the repository.
2. Installs Python 3.11.
3. Validates dashboard files.
4. Installs dashboard dependencies.
5. Runs a syntax check.
6. Validates required secrets.
7. Connects to Tailscale.
8. Starts Uvicorn.
9. Waits for the dashboard to become healthy.
10. Configures Tailscale Funnel.
11. Reports the public dashboard endpoints.
12. Tests public reachability.

---

# 🐳 Docker

The repository includes a `Dockerfile` based on:

```text
python:3.11-slim
```

Build:

```bash
docker build -t ayush-ai .
```

Run:

```bash
docker run --env-file .env ayush-ai
```

The container entry point is:

```bash
python3 bot.py
```

---

# ☁️ Fly.io

The repository also contains:

```text
fly.toml
```

The configured application name is:

```text
ayush-telegram-bot
```

The health check targets:

```text
/health
```

on the configured Flask service port.

---

# ❤️ Bot commands

The public command set includes:

```text
/start
/help
/reset
/stat
/stats
```

Administrative commands include:

```text
/addsudoauth
/addsudo
/removesudo
/sudolist
/broadcast
```

Administrative commands should only be used by authorized users.

---

# 📡 Health & monitoring endpoints

The bot includes a lightweight Flask health/telemetry server with routes for areas including:

```text
/health
/api/health
/api/providers
/api/activity
/api/users
/api/groups
/api/logs
```

The dashboard additionally exposes dashboard-specific API routes, including:

```text
/api/wallpaper
/api/dashboard
```

Exact route behavior should be treated as implementation-defined by the current source code.

---

# 🧠 AI response design

Ayush AI is designed for both casual and technical interactions.

For technical/academic prompts, the bot's response instructions emphasize:

- Clear explanations.
- Formula-first presentation where appropriate.
- Telegram-friendly mathematical notation.
- Unicode mathematical symbols instead of raw LaTeX delimiters in the final response.
- Structured answers for technical subjects.
- Image/OCR-aware handling where applicable.

Example Telegram-friendly formatting:

```text
λ = c / f

BER = 3.8 × 10⁻⁶

Pₑ = Q(√(2Eᵦ / N₀))
```

---

# 🔒 Security notes

### Never commit secrets

Do **not** place any of the following directly in source control:

```text
BOT_TOKEN
GEMINI_API_KEY_1
GEMINI_API_KEY_2
OPENAI_API_KEY
OPENROUTER_API_KEY
GROQ_API_KEY
CEREBRAS_API_KEY
GIST_TOKEN
TELEGRAM_CLIENT_SECRET
SESSION_SECRET
TAILSCALE_AUTHKEY
```

Use GitHub Actions Secrets, environment variables, or your hosting platform's secret manager.

### Dashboard authentication

The dashboard uses Telegram OIDC and a session middleware. Production deployments should use HTTPS and a strong persistent `SESSION_SECRET`.

### Sudo authentication

Dashboard-managed sudo credentials use salted PBKDF2-derived password records. Plaintext sudo passwords should never be committed to the repository.

---

# 🛠️ Technology stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Telegram | `python-telegram-bot` |
| AI | Gemini, OpenAI, OpenRouter, Groq, Cerebras |
| Bot health server | Flask |
| Dashboard | FastAPI + Uvicorn |
| Templates | Jinja2 |
| Authentication | Telegram OIDC + session middleware |
| Persistence | GitHub Gist |
| CI/CD | GitHub Actions |
| Container | Docker |
| Deployment config | Fly.io |
| Public dashboard tunnel | Tailscale Funnel |

---

# 📌 Operational model

```text
                    ┌─────────────────────┐
                    │     Telegram        │
                    │      Users          │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │     Ayush Bot       │
                    │   Python runtime    │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   AI Provider Chain │
                    └──────────┬──────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
       ┌──────────────┐                ┌──────────────┐
       │  Telegram    │                │  Telemetry   │
       │   Reply      │                │    + Gist    │
       └──────────────┘                └──────┬───────┘
                                             │
                                             ▼
                                      ┌──────────────┐
                                      │   Dashboard  │
                                      │   FastAPI    │
                                      └──────────────┘
```

---

# 🧪 Recommended validation before deployment

Run:

```bash
python -m py_compile bot.py
```

Then validate the dashboard:

```bash
python -m py_compile dashboard/dashboard.py
```

Install dependencies cleanly:

```bash
pip install -r requirements.txt
pip install -r dashboard/requirements.txt
```

Finally verify that all required deployment secrets are present.

---

# 🤝 Development

When modifying the project:

1. Preserve existing bot features unless a change explicitly requires removal.
2. Keep provider fallback behavior intact.
3. Avoid placing secrets in source files.
4. Run syntax checks before pushing.
5. Test both the bot and dashboard independently.
6. Review GitHub Actions logs after deployment.
7. Keep dashboard authentication configuration separate from public bot configuration.

---

# 📄 License

No explicit license file is included in the current repository snapshot.

If this project is intended for public reuse, add a `LICENSE` file and state the permitted usage clearly.

---

<div align="center">

### Built with Python, Telegram, AI providers, FastAPI, and GitHub Actions.

**Ayush AI**

</div>
