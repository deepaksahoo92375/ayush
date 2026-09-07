import os
import time
import random
import asyncio
import threading
import json
from functools import partial
from collections import defaultdict, deque

import requests
from dotenv import load_dotenv
from google import genai
from openai import OpenAI
from flask import Flask, jsonify
from flask_cors import CORS

from telegram import Update
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

async def ask_ai(messages, detected_lang="english"):
    loop = asyncio.get_running_loop()

    try:
        return await loop.run_in_executor(
            None,
            partial(
                _call_gemini,
                messages,
                300,
                0.8,
            ),
        )

    except Exception as e:
        print("Gemini Error:", repr(e))

    try:
        return await loop.run_in_executor(
            None,
            partial(
                _call_openai,
                messages,
                300,
                0.8,
            ),
        )

    except Exception as e:
        print("OpenAI Error:", repr(e))

    pool = FALLBACK_REPLIES.get(
        detected_lang,
        FALLBACK_REPLIES["english"],
    )

    return random.choice(pool)


# =========================================================
# TOXIC CHECK
# =========================================================

async def detect_toxic(text):
    lowered = text.lower()

    for word in TOXIC_WORDS:
        if word in lowered:
            return True

    moderation_messages = [
        {
            "role": "system",
            "content": (
                "Reply ONLY with YES or NO. "
                "Determine whether the message is toxic, "
                "abusive, hateful, sexual, or seriously offensive."
            ),
        },
        {
            "role": "user",
            "content": text,
        },
    ]

    loop = asyncio.get_running_loop()

    if gemini_client:
        try:
            answer = await loop.run_in_executor(
                None,
                partial(
                    _call_gemini,
                    moderation_messages,
                    5,
                    0,
                ),
            )

            return "yes" in answer.strip().lower()

        except Exception as e:
            print("Gemini moderation error:", repr(e))

    if openai_client:
        try:
            answer = await loop.run_in_executor(
                None,
                partial(
                    _call_openai,
                    moderation_messages,
                    5,
                    0,
                ),
            )

            return "yes" in answer.strip().lower()

        except Exception as e:
            print("OpenAI moderation error:", repr(e))

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

    await update.message.reply_text(
        "Hii 😊 I'm Ayush Nanda!\n\n"
        "You can chat with me normally. "
        "I can also help with questions, maths, physics, "
        "chemistry and general topics.\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/reset - Reset your chat memory\n"
        "/stats - Bot statistics"
    )

    update_stats(user_id, "casual")


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    await update.message.reply_text(
        "🤖 Ayush Bot Help\n\n"
        "Just send me a message and I'll reply.\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/reset - Clear your conversation memory\n"
        "/stats - Show bot statistics\n\n"
        "Owner/Sudo commands:\n"
        "/broadcast <message>\n"
        "/addsudo <user_id>\n"
        "/removesudo <user_id>\n"
        "/sudolist"
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
        "Memory reset successfully 😊"
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
        "📊 Ayush Bot Stats\n\n"
        f"Status: {data['status']}\n"
        f"Uptime: {hours}h {minutes}m\n"
        f"Total messages: {data['total_messages']}\n"
        f"Active users: {data['active_users']}\n"
        f"Messages today: {data['messages_today']}\n"
        f"AI replies: {data['ai_replies']}\n"
        f"Casual replies: {data['casual_replies']}\n"
        f"Toxic blocked: {data['toxic_blocked']}"
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
    chat_id = update.effective_chat.id if update.effective_chat else None

    text = sanitize_input(update.message.text)

    if not text:
        await update.message.reply_text(
            "Please send a message under 1000 characters."
        )
        return

    # Remember chats for broadcast.
    if chat_id is not None:
        known_chats[chat_id] = True

    # Rate limiting.
    now = time.time()
    previous = user_rate_limit.get(user_id, 0)

    if now - previous < RATE_LIMIT_SECONDS:
        return

    user_rate_limit[user_id] = now

    # Toxic check.
    try:
        toxic = await detect_toxic(text)
    except Exception as e:
        print("Toxic detection failure:", repr(e))
        toxic = False

    if toxic:
        increment_toxic()

        await update.message.reply_text(
            "Let's keep the conversation respectful 😊"
        )
        return

    detected_lang = detect_language(text)

    # Exact casual replies first.
    casual_key = text.lower().strip()

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

        await update.message.reply_text(reply)
        return

    # Clear stale memory after inactivity.
    if now - last_activity.get(user_id, 0) > SESSION_TIMEOUT:
        chat_memory[user_id].clear()

    last_activity[user_id] = now

    language_instruction = LANGUAGE_INSTRUCTIONS.get(
        detected_lang,
        LANGUAGE_INSTRUCTIONS["english"],
    )

    mode = detect_mode(text)

    system_prompt = (
        "You are Ayush Nanda, a friendly Telegram AI assistant. "
        "Be natural, helpful, warm and conversational. "
        "Do not claim to be a human when asked directly. "
        "Give accurate explanations and show useful steps for "
        "technical or academic questions. "
        "Keep normal casual replies reasonably concise. "
        "For numerical problems, show formulas and calculations "
        "clearly.\n\n"
        f"{language_instruction}\n\n"
        f"Current conversation mode: {mode}."
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    # Add recent memory.
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

        # Telegram messages have a practical size limit.
        if len(answer) > 4000:
            answer = answer[:3990] + "..."

        chat_memory[user_id].append(
            {"role": "user", "content": text}
        )
        chat_memory[user_id].append(
            {"role": "assistant", "content": answer}
        )

        update_stats(user_id, "ai")

        await update.message.reply_text(answer)

    except Exception as e:
        print("Message handler error:", repr(e))

        await update.message.reply_text(
            "Sorry yaar, something went wrong. Please try again 😅"
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    print(
        "Telegram error:",
        repr(context.error),
    )


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
