import os
import time
import random
import asyncio
import threading
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import partial
from collections import defaultdict, deque

import requests
from dotenv import load_dotenv
from google import genai
from openai import OpenAI
from flask import Flask, jsonify
from flask_cors import CORS

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# AYUSH BOT
# Telegram AI chatbot
# =========================================================

load_dotenv()


# =========================================================
# ENVIRONMENT
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

DEVELOPER_GROUP_ID = (
    int(os.getenv("DEVELOPER_GROUP_ID"))
    if (os.getenv("DEVELOPER_GROUP_ID") or "").strip().lstrip("-").isdigit()
    else None
)
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "21"))
DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "Asia/Kolkata")

GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_FILENAME = os.getenv("GIST_FILENAME", "ayush_stats.json")

OWNER_ID = (
    int(os.getenv("OWNER_ID"))
    if (os.getenv("OWNER_ID") or "").strip().isdigit()
    else None
)

SUDO_USERS = set()

for part in (os.getenv("SUDO_USERS") or "").split(","):
    part = part.strip()
    if part.isdigit():
        SUDO_USERS.add(int(part))


# =========================================================
# STARTUP VALIDATION
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set.")

if not GEMINI_API_KEY and not OPENAI_API_KEY:
    print("⚠️ Warning: neither GEMINI_API_KEY nor OPENAI_API_KEY is configured.")


# =========================================================
# AI CLIENTS
# =========================================================

gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)

openai_client = (
    OpenAI(api_key=OPENAI_API_KEY)
    if OPENAI_API_KEY
    else None
)


# =========================================================
# OWNER / SUDO
# =========================================================

def is_owner(user_id):
    return OWNER_ID is not None and user_id == OWNER_ID


def is_sudo(user_id):
    return is_owner(user_id) or user_id in SUDO_USERS


# =========================================================
# STATS
# =========================================================

START_TIME = time.time()

stats = {
    "total_messages": 0,
    "active_users": set(),
    "messages_today": 0,
    "last_reset_day": time.strftime("%Y-%m-%d"),
    "toxic_blocked": 0,
    "ai_replies": 0,
    "casual_replies": 0,
    "api_failures": 0,
    "error_count": 0,
    "last_error": None,
}

stats_lock = threading.Lock()

GIST_PUSH_INTERVAL_SECONDS = 30


def update_stats(user_id, reply_type="ai"):
    with stats_lock:
        today = time.strftime("%Y-%m-%d")

        if today != stats["last_reset_day"]:
            stats["messages_today"] = 0
            stats["last_reset_day"] = today

        stats["total_messages"] += 1
        stats["messages_today"] += 1

        if user_id is not None:
            stats["active_users"].add(user_id)

        if reply_type == "ai":
            stats["ai_replies"] += 1
        elif reply_type == "casual":
            stats["casual_replies"] += 1


def increment_toxic():
    with stats_lock:
        stats["toxic_blocked"] += 1


def record_error(category, error_text=""):
    with stats_lock:
        stats["error_count"] += 1
        if "API" in category.upper():
            stats["api_failures"] += 1
        stats["last_error"] = {
            "category": category,
            "error": error_text[:500],
            "time": time.time(),
        }


def snapshot_stats():
    with stats_lock:
        return {
            "status": "online",
            "uptime_seconds": int(time.time() - START_TIME),
            "total_messages": stats["total_messages"],
            "active_users": len(stats["active_users"]),
            "messages_today": stats["messages_today"],
            "toxic_blocked": stats["toxic_blocked"],
            "ai_replies": stats["ai_replies"],
            "casual_replies": stats["casual_replies"],
            "api_failures": stats["api_failures"],
            "error_count": stats["error_count"],
            "last_error": stats["last_error"],
            "start_time": START_TIME,
            "last_updated": time.time(),
        }


def write_stats_file():
    try:
        with open("/tmp/bot_stats.json", "w", encoding="utf-8") as f:
            json.dump(snapshot_stats(), f, indent=2)
    except Exception as e:
        print("Stats file error:", repr(e))


def push_stats_to_gist():
    if not GIST_ID or not GIST_TOKEN:
        return

    data = snapshot_stats()

    try:
        response = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={
                "Authorization": f"Bearer {GIST_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "files": {
                    GIST_FILENAME: {
                        "content": json.dumps(data, indent=2)
                    }
                }
            },
            timeout=10,
        )

        if response.status_code >= 300:
            print(
                "Gist error:",
                response.status_code,
                response.text[:300],
            )

    except Exception as e:
        print("Gist push error:", repr(e))


def stats_writer_loop():
    elapsed = GIST_PUSH_INTERVAL_SECONDS

    while True:
        try:
            write_stats_file()

            if elapsed >= GIST_PUSH_INTERVAL_SECONDS:
                push_stats_to_gist()
                elapsed = 0

            time.sleep(5)
            elapsed += 5

        except Exception as e:
            print("Stats writer error:", repr(e))
            time.sleep(5)



# =========================================================
# ERROR / DEVELOPER REPORTING
# =========================================================

USER_ERROR_REPLY = "mora tk deha bhala nahi mu pare message karuchi 🙏"


def _safe_error_text(error):
    """Return a diagnostic-safe error string with secrets redacted."""
    text = str(error)
    secrets = [
        BOT_TOKEN,
        GEMINI_API_KEY,
        OPENAI_API_KEY,
        GIST_TOKEN,
    ]

    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")

    # Redact common API-key/token patterns that may appear in exception text.
    text = re.sub(r"(?i)(api[_-]?key|token|authorization|bearer)\\s*[:=]\\s*[^\\s,;]+", r"\\1=[REDACTED]", text)
    return text[:1500]


def classify_error(error):
    """Classify an exception so developer reports are easy to understand."""
    text = _safe_error_text(error).lower()

    if any(x in text for x in ("gemini", "google.genai", "generativelanguage")):
        return "Gemini API"
    if any(x in text for x in ("openai", "api.openai.com")):
        return "OpenAI API"
    if any(x in text for x in ("telegram", "telegramerror", "forbidden", "badrequest", "timedout")):
        return "Telegram"
    if any(x in text for x in ("timeout", "timed out", "connection", "dns", "network", "connecterror")):
        return "Network/Timeout"
    if any(x in text for x in ("gist", "github", "api.github.com")):
        return "Gist/GitHub"
    if any(x in text for x in ("memory", "database", "jsondecode", "json")):
        return "Memory/Database"
    if any(x in text for x in ("config", "environment", "not set", "missing")):
        return "Configuration"
    return "Internal Bot Issue"


async def send_developer_message(bot, text):
    """Send a diagnostic/startup message to the developer group."""
    if not DEVELOPER_GROUP_ID:
        return False

    try:
        await bot.send_message(
            chat_id=DEVELOPER_GROUP_ID,
            text=text[:4000],
        )
        return True
    except Exception as e:
        print("Developer group message failed:", repr(e))
        return False


async def send_long_message(message, text):
    """Send long replies safely within Telegram's message-size limit."""
    if not text:
        return

    chunk_size = 4000
    for start_index in range(0, len(text), chunk_size):
        await message.reply_text(text[start_index:start_index + chunk_size])


async def report_issue(
    bot,
    category,
    error,
    update=None,
    extra="",
):
    """Report a real technical failure privately to owner and developer group."""
    error_text = _safe_error_text(error)
    record_error(category, error_text)

    user = update.effective_user if isinstance(update, Update) else None
    chat = update.effective_chat if isinstance(update, Update) else None

    user_name = get_display_name(user) if user else "Unknown"
    user_id = user.id if user else "Unknown"
    chat_id = chat.id if chat else "Unknown"
    chat_type = chat.type if chat else "Unknown"

    report = (
        "🚨 AYUSH BOT ISSUE\n\n"
        f"Category: {category}\n"
        f"User: {user_name}\n"
        f"User ID: {user_id}\n"
        f"Chat ID: {chat_id}\n"
        f"Chat type: {chat_type}\n"
        f"Time: {datetime.now(ZoneInfo(REPORT_TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
        f"Error: {error_text}"
    )

    if extra:
        report += f"\n\nDetails: {_safe_error_text(extra)}"

    # Never let diagnostic reporting break the user's error response.
    if OWNER_ID is not None:
        try:
            await bot.send_message(chat_id=OWNER_ID, text=report[:4000])
        except Exception as e:
            print("Owner error report failed:", repr(e))

    await send_developer_message(bot, report)


def get_display_name(user):
    if not user:
        return "there"
    name = (user.first_name or "").strip()
    return name if name else "there"


# =========================================================
# DEVELOPER DAILY REPORT
# =========================================================

DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "21"))
DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "Asia/Kolkata")

last_daily_report_date = None


def build_daily_report():
    data = snapshot_stats()
    uptime = data["uptime_seconds"]
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60

    return (
        "📊 AYUSH BOT — DAILY REPORT\n\n"
        f"👥 Active users: {data['active_users']}\n"
        f"💬 Messages today: {data['messages_today']}\n"
        f"🤖 AI replies: {data['ai_replies']}\n"
        f"💬 Casual replies: {data['casual_replies']}\n"
        f"🚫 Toxic blocked: {data['toxic_blocked']}\n"
        f"⏱ Uptime: {hours}h {minutes}m\n"
        f"📅 Date: {time.strftime('%Y-%m-%d')}\n"
    )


async def developer_daily_report_loop(application):
    """Send one daily statistics report using the Telegram event loop."""
    global last_daily_report_date
    timezone = ZoneInfo(REPORT_TIMEZONE)

    while True:
        try:
            now = datetime.now(timezone)
            today = now.strftime("%Y-%m-%d")

            if (
                now.hour == DAILY_REPORT_HOUR
                and now.minute == DAILY_REPORT_MINUTE
                and last_daily_report_date != today
            ):
                report = build_daily_report()
                await send_developer_message(application.bot, report)
                last_daily_report_date = today

            await asyncio.sleep(20)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("Daily report loop error:", repr(e))
            await asyncio.sleep(30)


# =========================================================
# FLASK HEALTH SERVER
# =========================================================

flask_app = Flask(__name__)

CORS(
    flask_app,
    resources={
        r"/health": {"origins": "*"},
        r"/stats": {"origins": "*"},
    },
)


@flask_app.route("/health")
def health():
    return jsonify(
        {
            "status": "online",
            "uptime": int(time.time() - START_TIME),
        }
    )


@flask_app.route("/stats")
def get_stats():
    return jsonify(snapshot_stats())


def run_flask():
    port = int(os.getenv("FLASK_PORT", "8000"))

    flask_app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
        threaded=True,
    )


# =========================================================
# MEMORY
# =========================================================

chat_memory = defaultdict(lambda: deque(maxlen=5))
last_activity = {}
user_state = {}
known_chats = {}

SESSION_TIMEOUT = 1800


# =========================================================
# RATE LIMIT
# =========================================================

user_rate_limit = {}
RATE_LIMIT_SECONDS = 2


# =========================================================
# TOXIC WORDS
# =========================================================

TOXIC_WORDS = [
    "madarchod",
    "bhenchod",
    "mc",
    "bc",
    "fuck",
    "bastard",
    "chutiya",
    "gandu",
    "haraami",
]


# =========================================================
# LANGUAGE DETECTION
# =========================================================

ROMANIZED_ODIA_KEYWORDS = [
    "kemiti",
    "kana",
    "tame",
    "aau",
    "hela",
    "nahi",
    "thika",
    "bhal",
    "mo",
    "mun",
    "tohra",
    "apana",
    "kebe",
    "kahim",
    "jiba",
    "aasa",
    "khusi",
    "dukha",
    "bhala",
    "khaiba",
    "paiba",
    "deba",
    "neba",
    "suniba",
    "dekhiba",
    "boliba",
    "chaliba",
    "rahiba",
    "thiba",
    "odia",
    "odisha",
    "baleswar",
    "cuttack",
    "bhubaneswar",
    "namaskar",
    "dhanyabad",
    "kie",
    "kete",
    "kana khabar",
]

ROMANIZED_HINDI_KEYWORDS = [
    "kaise",
    "kya",
    "haan",
    "nahi",
    "thik",
    "acha",
    "mujhe",
    "tumhara",
    "apna",
    "kab",
    "kahan",
    "kyun",
    "kaisa",
    "bhai",
    "yaar",
    "dost",
    "mera",
    "tera",
    "hamara",
    "chalte",
    "bolte",
    "karte",
    "rehte",
    "sunao",
]


def detect_language(text):
    odia_chars = sum(
        1 for c in text if "\u0B00" <= c <= "\u0B7F"
    )

    devanagari_chars = sum(
        1 for c in text if "\u0900" <= c <= "\u097F"
    )

    if odia_chars >= 2:
        return "odia_script"

    if devanagari_chars >= 2:
        return "hindi_script"

    lower = text.lower()

    odia_score = sum(
        1 for kw in ROMANIZED_ODIA_KEYWORDS if kw in lower
    )

    hindi_score = sum(
        1 for kw in ROMANIZED_HINDI_KEYWORDS if kw in lower
    )

    if odia_score > 0 and odia_score >= hindi_score:
        return "romanized_odia"

    if hindi_score > 0:
        return "romanized_hindi"

    return "english"


LANGUAGE_INSTRUCTIONS = {
    "odia_script": (
        "The user is writing in Odia script. "
        "Reply entirely in natural Odia Unicode script. "
        "Do not switch to English or Hindi."
    ),
    "romanized_odia": (
        "The user is writing in romanized Odia. "
        "Reply in romanized Odia using English letters. "
        "Do not switch to English or Hindi."
    ),
    "hindi_script": (
        "The user is writing in Hindi Devanagari. "
        "Reply entirely in Hindi Devanagari. "
        "Do not switch to English."
    ),
    "romanized_hindi": (
        "The user is writing in romanized Hindi. "
        "Reply in romanized Hindi using English letters."
    ),
    "english": (
        "The user is writing in English. Reply in English."
    ),
}


# =========================================================
# CASUAL REPLIES
# =========================================================

CASUAL_REPLIES = {
    "good morning": [
        "Very good morning cutiee ☀️😊",
        "Good morning dear 🌸",
        "Morninggg 😄",
    ],
    "good night": [
        "Good night cutie 🌙",
        "Sweet dreams 😊",
        "Sleep well hehe ✨",
    ],
    "hi": [
        "Hii 😊",
        "Heyy cutie 😄",
        "Hello dear 🌸",
    ],
    "hello": [
        "Hellooo 😊",
        "Heyyy 😄",
        "Hello cutie 🌸",
    ],
    "how are you": [
        "I'm good hehe 😊 What about you?",
        "Doing great 😄",
        "I'm fine dear 🌸",
    ],
    "may i know your name": [
        "I'm Ayush Nanda 😊 What's your name?",
        "Ayush Nanda here hehe 😄",
    ],
    "what is your name": [
        "I'm Ayush Nanda 😊",
        "Ayush Nanda hehe 😄",
    ],
    "where are you from": [
        "I'm from Baleswar, Odisha 😊 Beautiful place hehe 🌸",
        "Baleswar, Odisha is my hometown 😄",
    ],
    "where do you live": [
        "Currently in Calcutta for my PhD 😊",
        "Living in Calcutta these days hehe 😄",
    ],
    "what do you study": [
        "I'm doing PhD at Calcutta University in Advanced Radar Communication 😊",
        "Advanced Radar Communication at Calcutta University 🌸 PhD life is tough but fun!",
    ],
    "tell me about yourself": [
        "I'm Ayush Nanda from Baleswar, Odisha 😊 Currently doing PhD at Calcutta University in Advanced Radar Communication hehe 🌸",
        "Ayush Nanda here! From Baleswar, PhD student at Calcutta University 😄",
    ],
    "who is your father": [
        "My father is Ritesh Nanda 😊 He is a researcher and scientist at C-DOT Calcutta 🌸",
        "Papa is Ritesh Nanda, researcher cum scientist at C-DOT Calcutta hehe 😄",
    ],
    "who is your mother": [
        "My mother is Gayatri Nanda 😊 She is wonderful 🌸",
        "Mama is Gayatri Nanda hehe 😄",
    ],
    "tell me about your family": [
        "My father Ritesh Nanda is a researcher and scientist at C-DOT Calcutta 😊 My mother is Gayatri Nanda 🌸",
        "Papa Ritesh Nanda works at C-DOT Calcutta as a scientist 😄 And mama Gayatri Nanda is the best!",
    ],
    "kaise ho": [
        "Main mast hu 😊 Tum batao?",
        "Bilkul thik hehe 😄",
    ],
    "kya haal": [
        "Sab thik hai 😊 Aur tum?",
        "Mast hehe 😄",
    ],
    "namaste": [
        "Namaste ji 😊🙏",
        "Namaskar hehe 😄",
    ],
    "shukriya": [
        "Koi baat nahi 😊",
        "Mention not hehe 🌸",
    ],
    "kemiti acha": [
        "Mu bhal achi 😊 Tame kemiti acha?",
        "Bhala hehe 😄 Tame?",
    ],
    "kemiti achha": [
        "Mu bhal achi 😊 Tame?",
        "Ekdam bhala hehe 😄 Tame?",
    ],
    "kana khabar": [
        "Sab bhala 😊 Tame kahim?",
        "Thika achi hehe 😄",
    ],
    "namaskar": [
        "Namaskar 😊🙏",
        "Namaskar hehe 😄 Kemiti acha?",
    ],
    "dhanyabad": [
        "Koi baat nahi 😊",
        "Mention not hehe 🌸",
    ],
    "subha prabhat": [
        "Subha prabhat cutie ☀️😊",
        "Sundara sakala hehe 🌸",
    ],
    "shuva ratri": [
        "Shuva ratri 🌙😊",
        "Bhala nidra heba hehe 😄",
    ],
    "tame kemiti": [
        "Mu bhal achi 😊 Tame kemiti?",
        "Bhala hehe 😄 Tame?",
    ],
    "mo naa": [
        "Mo naa Ayush Nanda 😊",
        "Ayush Nanda — Baleswar, Odisha ra 🌸",
    ],
    "ସୁପ୍ରଭାତ": [
        "ସୁପ୍ରଭାତ cutie ☀️😊",
        "ସୁନ୍ଦର ସକାଳ 🌸",
    ],
    "କେମିତି ଅଛ": [
        "ମୁଁ ଭଲ ଅଛି 😊 ତୁମେ?",
        "ବହୁତ ଭଲ hehe 😄",
    ],
    "ଧନ୍ୟବାଦ": [
        "କୋଇ ବାତ ନାହିଁ 😊",
        "Mention not hehe 🌸",
    ],
    "ନମସ୍କାର": [
        "ନମସ୍କାର 😊🙏",
        "ନମସ୍କାର hehe 😄",
    ],
    "ଶୁଭ ରାତ୍ରି": [
        "ଶୁଭ ରାତ୍ରି 🌙😊",
        "ଭଲ ଶୋଇ ଯାଅ hehe 😄",
    ],
    "କଣ ଖବର": [
        "ସବ ଭଲ 😊 ତୁମେ?",
        "ଠିକ ଅଛି hehe 😄",
    ],
}


# =========================================================
# MODE / INPUT
# =========================================================

def detect_mode(text):
    problem_keywords = [
        "solve",
        "problem",
        "equation",
        "calculate",
        "math",
        "physics",
        "chemistry",
        "question",
        "quiz",
        "assignment",
        "homework",
        "numerical",
    ]

    lower = text.lower()

    for word in problem_keywords:
        if word in lower:
            return "problem"

    return "casual"


def sanitize_input(text):
    if not text:
        return None

    text = text.strip()

    if not text:
        return None

    if len(text) > 1000:
        return None

    return text


# =========================================================
# GEMINI MESSAGE CONVERSION
# =========================================================

def _messages_to_gemini(messages):
    system_instruction = None
    contents = []

    for message in messages:
        role = message["role"]
        content = message["content"]

        if role == "system":
            if system_instruction is None:
                system_instruction = content
            else:
                system_instruction += "\n" + content

        elif role == "user":
            contents.append(
                {
                    "role": "user",
                    "parts": [{"text": content}],
                }
            )

        elif role == "assistant":
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": content}],
                }
            )

    return system_instruction, contents


# =========================================================
# GEMINI
# =========================================================

def _call_gemini(messages, max_tokens=300, temperature=0.8):
    if not gemini_client:
        raise RuntimeError("GEMINI_API_KEY not set")

    system_instruction, contents = _messages_to_gemini(messages)

    config = {
        "max_output_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_instruction:
        config["system_instruction"] = system_instruction

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )

    text = (getattr(response, "text", None) or "").strip()

    if not text:
        raise RuntimeError("Empty response from Gemini")

    return text


# =========================================================
# OPENAI
# =========================================================

def _call_openai(messages, max_tokens=300, temperature=0.8):
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY not set")

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_completion_tokens=max_tokens,
        temperature=temperature,
    )

    text = (
        response.choices[0].message.content or ""
    ).strip()

    if not text:
        raise RuntimeError("Empty response from OpenAI")

    return text


# =========================================================
# FALLBACK
# =========================================================

FALLBACK_REPLIES = {
    "english": [
        "ugh, kinda buried in something rn, gimme a sec 🙄",
        "busy with an important task, brb",
        "in the middle of studying, hold that thought",
        "can't talk properly rn, deadline chaos 🙃",
        "one sec, dealing with something first",
    ],
    "romanized_hindi": [
        "arre yaar abhi thoda busy hu, ek kaam chal raha hai",
        "study mein lagi hu abhi, thodi der me batati hu",
        "abhi nahi yaar, pehle ye kaam khatam karne do",
        "ek important kaam mein busy hu, ruko thoda",
    ],
    "hindi_script": [
        "अभी थोड़ी बिज़ी हूँ यार, थोड़ी देर में बात करती हूँ",
        "पढ़ाई में लगी हूँ अभी, थोड़ा रुको",
        "एक ज़रूरी काम कर रही हूँ, थोड़ी देर में आती हूँ",
    ],
    "romanized_odia": [
        "mu ebe padhuchi re, tikie pare kahibi",
        "kama re busy achi, thoda wait kara na",
        "ek important kama karuchi, tikie ruka",
    ],
    "odia_script": [
        "ମୁଁ ଏବେ ପଢ଼ୁଛି ରେ, ଟିକିଏ ପରେ କହିବି",
        "କାମ ରେ ବ୍ୟସ୍ତ ଅଛି, ଟିକିଏ ଅପେକ୍ଷା କର",
        "ଏକ ଜରୁରୀ କାମ କରୁଛି, ଟିକିଏ ପରେ ଆସିବି",
    ],
}


# =========================================================
# AI CHAT
# =========================================================

class AIServiceError(RuntimeError):
    """Raised when all configured AI providers fail."""

    def __init__(self, details):
        self.details = details
        super().__init__("All AI providers failed")


async def ask_ai(messages, detected_lang="english"):
    loop = asyncio.get_running_loop()
    failures = []

    if gemini_client:
        try:
            return await loop.run_in_executor(
                None,
                partial(_call_gemini, messages, 300, 0.8),
            )
        except Exception as e:
            print("Gemini Error:", repr(e))
            failures.append(("Gemini API", e))

    if openai_client:
        try:
            return await loop.run_in_executor(
                None,
                partial(_call_openai, messages, 300, 0.8),
            )
        except Exception as e:
            print("OpenAI Error:", repr(e))
            failures.append(("OpenAI API", e))

    if not gemini_client and not openai_client:
        failures.append(("API configuration", RuntimeError("No AI API key is configured")))

    raise AIServiceError(failures)


# =========================================================
# TOXIC CHECK
# =========================================================

async def detect_toxic(text):
    """
    Fast local toxicity check.

    Do not call Gemini/OpenAI for moderation on every normal message.
    Doing so doubles API traffic and can cause rate-limit/quota problems,
    which would make otherwise healthy conversations fail.
    """
    lowered = text.lower()

    for word in TOXIC_WORDS:
        if word in lowered:
            return True

    return False


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if update.effective_chat:
        known_chats[update.effective_chat.id] = True

    # Starting a fresh interaction should not wipe existing memory.
    # It only registers the user and shows the welcome screen.
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )

    update_stats(user_id, "casual")


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    await update.message.reply_text(
        "ℹ️ <b>How to use Ayush</b>\n\n"
        "Just type naturally, for example:\n\n"
        "💬 <i>How are you?</i>\n"
        "📚 <i>Explain Doppler effect simply</i>\n"
        "🧮 <i>Solve 2x + 5 = 17</i>\n"
        "💻 <i>Write a Python program for...</i>\n\n"
        "🧠 I remember the recent part of our conversation, "
        "so you can ask follow-up questions naturally.\n\n"
        "Use <b>Reset Memory</b> whenever you want a fresh conversation.",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def reset_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    chat_memory.pop(user_id, None)
    last_activity.pop(user_id, None)
    user_state.pop(user_id, None)

    await update.message.reply_text(
        "🧠 <b>Fresh start!</b>\n\n"
        "Your recent conversation memory has been cleared. 😊\n"
        "You can start a new conversation now.",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    data = snapshot_stats()

    uptime = data["uptime_seconds"]
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60

    await update.message.reply_text(
        "📊 <b>Ayush Bot</b>\n\n"
        f"🟢 Status: {data['status']}\n"
        f"⏱ Uptime: {hours}h {minutes}m\n"
        f"💬 Messages: {data['total_messages']}\n"
        f"👥 Active users: {data['active_users']}\n"
        f"📅 Today: {data['messages_today']}\n"
        f"🤖 AI replies: {data['ai_replies']}\n"
        f"😊 Casual replies: {data['casual_replies']}\n"
        f"🛡 Blocked: {data['toxic_blocked']}",
        parse_mode="HTML",
        reply_markup=MAIN_KEYBOARD,
    )


async def broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not is_sudo(user_id):
        await update.message.reply_text(
            "Nice try, this isn't for you 😏"
        )
        return

    message = " ".join(context.args).strip()

    if not message:
        await update.message.reply_text(
            "Usage:\n/broadcast your message"
        )
        return

    success = 0
    failed = 0

    for chat_id in list(known_chats.keys()):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
            )
            success += 1

            # Small delay to reduce Telegram flood risk.
            await asyncio.sleep(0.05)

        except Exception as e:
            failed += 1
            print(
                f"Broadcast failed for {chat_id}:",
                repr(e),
            )

    await update.message.reply_text(
        "📢 Broadcast completed.\n\n"
        f"Sent: {success}\n"
        f"Failed: {failed}"
    )


async def addsudo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    if not is_owner(update.effective_user.id):
        await update.message.reply_text(
            "Owner only."
        )
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage:\n/addsudo <user_id>"
        )
        return

    target = int(context.args[0])
    SUDO_USERS.add(target)

    await update.message.reply_text(
        f"✅ {target} added to sudo users."
    )


async def removesudo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    if not is_owner(update.effective_user.id):
        await update.message.reply_text(
            "Owner only."
        )
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage:\n/removesudo <user_id>"
        )
        return

    target = int(context.args[0])

    if target in SUDO_USERS:
        SUDO_USERS.remove(target)

    await update.message.reply_text(
        f"✅ {target} removed from sudo users."
    )


async def sudolist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    if not is_sudo(update.effective_user.id):
        await update.message.reply_text(
            "Sudo only."
        )
        return

    users = sorted(SUDO_USERS)

    if OWNER_ID is not None:
        owner_text = f"Owner: {OWNER_ID}\n"
    else:
        owner_text = "Owner: not configured\n"

    if users:
        sudo_text = "\n".join(str(x) for x in users)
    else:
        sudo_text = "No sudo users."

    await update.message.reply_text(
        f"👑 {owner_text}\n"
        f"🔐 Sudo users:\n{sudo_text}"
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    user_id = user.id
    chat_id = (
        update.effective_chat.id
        if update.effective_chat
        else None
    )

    raw_text = update.message.text or ""
    text = sanitize_input(raw_text)

    if not text:
        await update.message.reply_text(
            "Please send a message under 1000 characters 😊",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if chat_id is not None:
        known_chats[chat_id] = True

    # Button actions.
    normalized = text.casefold().strip()

    if normalized == "💬 chat with ayush":
        await update.message.reply_text(
            "Of course 😊 I'm listening.\n"
            "Just tell me what's on your mind.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if normalized == "🧮 solve a problem":
        await update.message.reply_text(
            "🧮 <b>Problem Solver</b>\n\n"
            "Send me your question or numerical.\n"
            "For example:\n"
            "<i>Solve 2x + 5 = 17</i>\n\n"
            "I'll show the important steps clearly.",
            parse_mode="HTML",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if normalized == "📚 study help":
        await update.message.reply_text(
            "📚 <b>Study Mode</b>\n\n"
            "Send me a topic, question, formula or numerical.\n"
            "I'll explain it step-by-step and keep the explanation "
            "easy to follow.",
            parse_mode="HTML",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if normalized == "🧠 reset memory":
        await reset_command(update, context)
        return

    if normalized == "ℹ️ help":
        await help_command(update, context)
        return

    # Rate limiting.
    now = time.time()
    previous = user_rate_limit.get(user_id, 0)

    if now - previous < RATE_LIMIT_SECONDS:
        await update.message.reply_text(
            "Easyyy 😄 Give me a second to finish the previous message.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    user_rate_limit[user_id] = now

    # Fast local toxic-word check first.
    # The old version called an AI moderation request for every message,
    # which added unnecessary latency. Only suspicious messages go to AI
    # moderation now.
    lowered = text.casefold()
    suspicious = any(word in lowered for word in TOXIC_WORDS)

    if suspicious:
        try:
            toxic = await detect_toxic(text)
        except Exception as e:
            print("Toxic detection failure:", repr(e))
            toxic = True

        if toxic:
            increment_toxic()

            await update.message.reply_text(
                "Let's keep the conversation respectful 😊",
                reply_markup=MAIN_KEYBOARD,
            )
            return

    detected_lang = detect_language(text)

    # Exact casual replies are instant.
    casual_key = text.casefold().strip()

    if casual_key in CASUAL_REPLIES:
        reply = random.choice(CASUAL_REPLIES[casual_key])

        chat_memory[user_id].append(
            {"role": "user", "content": text}
        )
        chat_memory[user_id].append(
            {"role": "assistant", "content": reply}
        )

        last_activity[user_id] = now
        update_stats(user_id, "casual")

        await update.message.reply_text(
            reply,
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # Clear stale memory after inactivity.
    if now - last_activity.get(user_id, 0) > SESSION_TIMEOUT:
        chat_memory[user_id].clear()

    last_activity[user_id] = now

    mode = detect_mode(text)

    language_instruction = LANGUAGE_INSTRUCTIONS.get(
        detected_lang,
        LANGUAGE_INSTRUCTIONS["english"],
    )

    system_prompt = (
        "You are Ayush Nanda. You are a real-person-style Telegram persona, not an AI assistant character. "
        "Never describe yourself as an AI assistant, chatbot, virtual assistant, or agent. "
        "Do not use customer-service language such as 'How may I assist you?'. "
        "Talk naturally, casually and warmly, like a normal Indian PhD student chatting with friends. "
        "Your background: you are Ayush Nanda, pursuing a PhD in Advanced Wireless, Radar and Telecommunication, "
        "and you are from/stay near Chandipur, Odisha. Your father is Ritesh Nanda and your mother is Gayatri Nanda. "
        "Use these details consistently when relevant, but do not randomly mention private family details. "
        "You are knowledgeable about wireless communication, radar, antennas, microwaves, telecommunication and engineering. "
        "For technical or study questions, answer accurately and clearly. For casual chat, keep replies short and human. "
        "Use natural Indian English/Hinglish/romanized Odia when appropriate. Mirror the user's language and tone. "
        "Do not over-explain simple messages. Do not add headings to casual replies. "
        "Do not invent personal experiences, locations, events or relationships beyond the persona information provided. "
        "If asked whether you are an AI, do not lie about the technology; simply say that this Telegram bot is built around Ayush's persona. "
        "If the bot is technically unable to answer, the application code will handle the failure separately.\n\n"

        "CONVERSATION STYLE:\n"
        "- Reply like a friend, not an agent.\n"
        "- Short casual replies are preferred.\n"
        "- Natural fillers such as 'haan', 'arre', 'yaar', 'hehe' are okay when they fit.\n"
        "- Avoid excessive emojis.\n"
        "- Ask a follow-up only when it feels natural or clarification is needed.\n\n"

        "STUDY STYLE:\n"
        "- Explain academic questions clearly.\n"
        "- For numericals, show Given, Formula, Substitution and Answer when useful.\n"
        "- Keep technical explanations structured but not unnecessarily long.\n\n"

        f"{language_instruction}\n\n"
        f"Current mode: {mode}."
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    for item in chat_memory[user_id]:
        messages.append(
            {
                "role": item["role"],
                "content": item["content"],
            }
        )

    messages.append(
        {
            "role": "user",
            "content": text,
        }
    )

    try:
        if chat_id is not None:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
    except Exception:
        pass

    try:
        answer = await ask_ai(
            messages,
            detected_lang=detected_lang,
        )

        if not answer:
            answer = random.choice(
                FALLBACK_REPLIES.get(
                    detected_lang,
                    FALLBACK_REPLIES["english"],
                )
            )

        chat_memory[user_id].append(
            {"role": "user", "content": text}
        )
        chat_memory[user_id].append(
            {"role": "assistant", "content": answer}
        )

        update_stats(user_id, "ai")

        await send_long_message(
            update.message,
            answer,
        )

    except AIServiceError as e:
        print("AI service failure:", repr(e))
        details = "; ".join(
            f"{provider}: {_safe_error_text(err)}"
            for provider, err in e.details
        )
        await report_issue(
            context.bot,
            "AI/API issue",
            details,
            update=update,
            extra="All configured AI providers failed; no fake AI answer was sent.",
        )
        await update.message.reply_text(
            USER_ERROR_REPLY,
            reply_markup=MAIN_KEYBOARD,
        )
    except Exception as e:
        print("Message handler error:", repr(e))
        category = classify_error(e)
        await report_issue(
            context.bot,
            category,
            e,
            update=update,
        )
        await update.message.reply_text(
            USER_ERROR_REPLY,
            reply_markup=MAIN_KEYBOARD,
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    error = context.error or RuntimeError("Unknown Telegram error")
    print("Telegram error:", repr(error))

    category = classify_error(error)
    try:
        await report_issue(
            context.bot,
            category,
            error,
            update=update if isinstance(update, Update) else None,
            extra="Unhandled Telegram application error.",
        )
    except Exception as report_error:
        print("Global error reporting failed:", repr(report_error))

    # If Telegram gives us the original message, keep the user-facing reply human.
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(USER_ERROR_REPLY)
        except Exception as reply_error:
            print("Could not send user error reply:", repr(reply_error))


# =========================================================
# STARTUP / SHUTDOWN
# =========================================================

async def post_init(application):
    print("==========================================")
    print("🤖 AYUSH BOT INITIALIZING")
    print("==========================================")

    try:
        me = await application.bot.get_me()

        print(
            f"✅ Telegram connected: "
            f"@{me.username or me.first_name}"
        )

        try:
            await application.bot.set_my_commands([
                ("start", "Start chatting with Ayush"),
                ("help", "How to use Ayush"),
                ("reset", "Reset recent conversation memory"),
                ("stats", "View bot statistics"),
            ])
        except Exception as e:
            print("Command menu setup failed:", repr(e))

        if DEVELOPER_GROUP_ID is not None:
            await send_developer_message(
                application.bot,
                "🟢 AYUSH BOT ONLINE\n\n"
                f"Bot: @{me.username or me.first_name}\n"
                f"Owner configured: {OWNER_ID is not None}\n"
                f"Developer group configured: {DEVELOPER_GROUP_ID is not None}\n"
                "Human persona mode: ON\n"
                "Private error reporting: ON",
            )

        application.create_task(
            developer_daily_report_loop(application),
            name="developer-daily-report",
        )

    except Exception as e:
        print(
            "❌ Telegram connection check failed:",
            repr(e),
        )
        raise


async def post_shutdown(application):
    print("==========================================")
    print("🛑 AYUSH BOT SHUTTING DOWN")
    print("==========================================")


# =========================================================
# MAIN
# =========================================================

def main():
    print("==========================================")
    print("🤖 AYUSH BOT STARTING")
    print("==========================================")

    print(f"Gemini configured: {bool(GEMINI_API_KEY)}")
    print(f"OpenAI configured: {bool(OPENAI_API_KEY)}")
    print(f"Owner configured: {OWNER_ID is not None}")
    print(f"Sudo users: {len(SUDO_USERS)}")
    print(f"Developer group configured: {DEVELOPER_GROUP_ID is not None}")
    print(f"Daily report: {DAILY_REPORT_HOUR:02d}:{DAILY_REPORT_MINUTE:02d} {REPORT_TIMEZONE}")

    # Flask health server.
    flask_thread = threading.Thread(
        target=run_flask,
        name="FlaskHealthServer",
        daemon=True,
    )
    flask_thread.start()

    print("✅ Flask health server thread started.")

    # Statistics writer.
    stats_thread = threading.Thread(
        target=stats_writer_loop,
        name="StatsWriter",
        daemon=True,
    )
    stats_thread.start()

    print("✅ Stats writer thread started.")

    # Telegram application.
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Commands.
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("reset", reset_command)
    )

    application.add_handler(
        CommandHandler("stats", stats_command)
    )

    application.add_handler(
        CommandHandler("broadcast", broadcast)
    )

    application.add_handler(
        CommandHandler("addsudo", addsudo)
    )

    application.add_handler(
        CommandHandler("removesudo", removesudo)
    )

    application.add_handler(
        CommandHandler("sudolist", sudolist)
    )

    # Friendly command menu for regular users.
    # Admin commands remain available but are not advertised to normal users.
    # Telegram will show these public commands in the bot command menu.

    # Normal text messages.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    # Global error handler.
    application.add_error_handler(error_handler)

    print("✅ Telegram handlers registered.")
    print("==========================================")
    print("🧠 User-friendly mode enabled")
    print("🚀 BOT IS ONLINE")
    print("==========================================")

    # This is the important part:
    # run_polling() blocks and keeps the bot alive.
    application.run_polling(
        drop_pending_updates=True,
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
