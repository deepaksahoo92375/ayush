import os
import time
import random
import asyncio
import threading
import json
from functools import partial
from collections import defaultdict, deque

from dotenv import load_dotenv
from google import genai
from openai import OpenAI
from flask import Flask, jsonify
from flask_cors import CORS
import requests

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction


# =========================================
# LOAD ENV
# =========================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# =========================================
# OWNER / SUDO ACCESS CONTROL
# =========================================

def _parse_id_list(raw):
    ids = set()

    for part in (raw or "").split(","):
        part = part.strip()

        if part.isdigit():
            ids.add(int(part))

    return ids


OWNER_ID = (
    int(os.getenv("OWNER_ID"))
    if (os.getenv("OWNER_ID") or "").strip().isdigit()
    else None
)

sudo_users = _parse_id_list(os.getenv("SUDO_USERS"))


def is_owner(user_id):
    return OWNER_ID is not None and user_id == OWNER_ID


def is_sudo(user_id):
    return is_owner(user_id) or user_id in sudo_users


# =========================================
# AI CLIENTS
# =========================================

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


# =========================================
# GITHUB GIST
# =========================================

GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_FILENAME = os.getenv(
    "GIST_FILENAME",
    "ayush_stats.json"
)

GIST_PUSH_INTERVAL_SECONDS = 30


# =========================================
# STATS
# =========================================

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


def update_stats(user_id, reply_type="ai"):
    with stats_lock:

        today = time.strftime("%Y-%m-%d")

        if today != stats["last_reset_day"]:
            stats["messages_today"] = 0
            stats["last_reset_day"] = today

        stats["total_messages"] += 1
        stats["messages_today"] += 1
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

    data = snapshot_stats()

    try:

        with open("/tmp/bot_stats.json", "w") as f:
            json.dump(data, f)

    except Exception as e:
        print("Stats file error:", e)


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
                        "content": json.dumps(
                            data,
                            indent=2
                        )
                    }
                }
            },
            timeout=10,
        )

        if response.status_code >= 300:
            print(
                "Gist error:",
                response.status_code,
                response.text[:300]
            )

    except Exception as e:
        print("Gist push error:", e)


def stats_writer_loop():

    elapsed = GIST_PUSH_INTERVAL_SECONDS

    while True:

        write_stats_file()

        if elapsed >= GIST_PUSH_INTERVAL_SECONDS:

            push_stats_to_gist()

            elapsed = 0

        time.sleep(5)
        elapsed += 5


# =========================================
# FLASK HEALTH SERVER
# =========================================

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

    port = int(
        os.getenv(
            "FLASK_PORT",
            "8000"
        )
    )

    flask_app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
        threaded=True,
    )


# =========================================
# MEMORY
# =========================================

chat_memory = defaultdict(
    lambda: deque(maxlen=5)
)

last_activity = {}
user_state = {}

known_chats = {}

SESSION_TIMEOUT = 1800


# =========================================
# RATE LIMIT
# =========================================

user_rate_limit = {}

RATE_LIMIT_SECONDS = 2


# =========================================
# TOXIC WORDS
# =========================================

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


# =========================================
# LANGUAGE DETECTION
# =========================================

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
        1
        for c in text
        if "\u0B00" <= c <= "\u0B7F"
    )

    devanagari_chars = sum(
        1
        for c in text
        if "\u0900" <= c <= "\u097F"
    )

    if odia_chars >= 2:
        return "odia_script"

    if devanagari_chars >= 2:
        return "hindi_script"

    lower = text.lower()

    odia_score = sum(
        1
        for kw in ROMANIZED_ODIA_KEYWORDS
        if kw in lower
    )

    hindi_score = sum(
        1
        for kw in ROMANIZED_HINDI_KEYWORDS
        if kw in lower
    )

    if odia_score > 0 and odia_score >= hindi_score:
        return "romanized_odia"

    if hindi_score > 0:
        return "romanized_hindi"

    return "english"


LANGUAGE_INSTRUCTIONS = {

    "odia_script":
        "The user is writing in Odia script. "
        "Reply entirely in natural Odia Unicode script. "
        "Do not switch to English or Hindi.",

    "romanized_odia":
        "The user is writing in romanized Odia. "
        "Reply in romanized Odia using English letters. "
        "Do not switch to English or Hindi.",

    "hindi_script":
        "The user is writing in Hindi Devanagari. "
        "Reply entirely in Hindi Devanagari. "
        "Do not switch to English.",

    "romanized_hindi":
        "The user is writing in romanized Hindi. "
        "Reply in romanized Hindi using English letters.",

    "english":
        "The user is writing in English. Reply in English.",
}


# =========================================
# CASUAL REPLIES
# =========================================

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
        "Bhala hehe 😄",
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


# =========================================
# MODE
# =========================================

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


# =========================================
# SANITIZE
# =========================================

def sanitize_input(text):

    if not text:
        return None

    text = text.strip()

    if not text:
        return None

    if len(text) > 1000:
        return None

    return text


# =========================================
# GEMINI MESSAGE CONVERSION
# =========================================

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
                    "parts": [
                        {
                            "text": content
                        }
                    ],
                }
            )

        elif role == "assistant":

            contents.append(
                {
                    "role": "model",
                    "parts": [
                        {
                            "text": content
                        }
                    ],
                }
            )

    return system_instruction, contents


# =========================================
# GEMINI
# =========================================

def _call_gemini(
    messages,
    max_tokens=300,
    temperature=0.8
):

    if not gemini_client:
        raise RuntimeError(
            "GEMINI_API_KEY not set"
        )

    system_instruction, contents = (
        _messages_to_gemini(messages)
    )

    response = gemini_client.models.generate_content(

        model=GEMINI_MODEL,

        contents=contents,

        config={
            "system_instruction": system_instruction,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        },
    )

    text = (
        getattr(response, "text", None)
        or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "Empty response from Gemini"
        )

    return text


# =========================================
# OPENAI
# =========================================

def _call_openai(
    messages,
    max_tokens=300,
    temperature=0.8
):

    if not openai_client:
        raise RuntimeError(
            "OPENAI_API_KEY not set"
        )

    response = (
        openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_completion_tokens=max_tokens,
            temperature=temperature,
        )
    )

    text = (
        response.choices[0]
        .message.content
        or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "Empty response from OpenAI"
        )

    return text


# =========================================
# FALLBACK
# =========================================

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


# =========================================
# AI CHAT
# =========================================

async def ask_ai(
    messages,
    detected_lang="english"
):

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

        print(
            "Gemini Error:",
            repr(e)
        )

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

        print(
            "OpenAI Error:",
            repr(e)
        )

    pool = FALLBACK_REPLIES.get(
        detected_lang,
        FALLBACK_REPLIES["english"],
    )

    return random.choice(pool)


# =========================================
# TOXIC CHECK
# =========================================

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
                "Determine whether the message is "
                "toxic, abusive, hateful, sexual, "
                "or seriously offensive."
            ),
        },

        {
            "role": "user",
            "content": text,
        },
    ]

    loop = asyncio.get_running_loop()

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

        return (
            "yes"
            in answer.strip().lower()
        )

    except Exception as e:

        print(
            "Gemini moderation error:",
            repr(e)
        )

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

        return (
            "yes"
            in answer.strip().lower()
        )

    except Exception as e:

        prin