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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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


def write_stats_file():
    with stats_lock:
        data = {
            "status": "online",
            "uptime_seconds": int(time.time() - START_TIME),
            "total_messages": stats["total_messages"],
            "active_users": len(stats["active_users"]),
            "messages_today": stats["messages_today"],
            "toxic_blocked": stats["toxic_blocked"],
            "ai_replies": stats["ai_replies"],
            "casual_replies": stats["casual_replies"],
            "start_time": START_TIME,
        }
    try:
        with open("/tmp/bot_stats.json", "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def stats_writer_loop():
    while True:
        write_stats_file()
        time.sleep(5)


# =========================================
# FLASK KEEP-ALIVE SERVER
# =========================================

flask_app = Flask(__name__)


@flask_app.route("/health")
def health():
    return jsonify({"status": "online", "uptime": int(time.time() - START_TIME)})


@flask_app.route("/stats")
def get_stats():
    with stats_lock:
        return jsonify({
            "status": "online",
            "uptime_seconds": int(time.time() - START_TIME),
            "total_messages": stats["total_messages"],
            "active_users": len(stats["active_users"]),
            "messages_today": stats["messages_today"],
            "toxic_blocked": stats["toxic_blocked"],
            "ai_replies": stats["ai_replies"],
            "casual_replies": stats["casual_replies"],
            "start_time": START_TIME,
        })


def run_flask():
    port = int(os.getenv("FLASK_PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)


# =========================================
# MEMORY
# =========================================

chat_memory = defaultdict(lambda: deque(maxlen=5))
last_activity = {}
user_state = {}

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
    "kemiti", "kana", "tame", "aau", "hela", "nahi", "thika", "bhal",
    "mo", "mun", "tohra", "apana", "kebe", "kahim", "jiba", "aasa",
    "khusi", "dukha", "bhala", "khaiba", "paiba", "deba", "neba",
    "suniba", "dekhiba", "boliba", "chaliba", "rahiba", "thiba",
    "odia", "odisha", "baleswar", "cuttack", "bhubaneswar",
    "namaskar", "dhanyabad", "kie", "kete", "kana khabar",
]

ROMANIZED_HINDI_KEYWORDS = [
    "kaise", "kya", "haan", "nahi", "thik", "acha", "mujhe",
    "tumhara", "apna", "kab", "kahan", "kyun", "kaisa",
    "bhai", "yaar", "dost", "mera", "tera", "hamara",
    "chalte", "bolte", "karte", "rehte", "sunao",
]


def detect_language(text: str) -> str:
    """Detect language from Unicode script ranges and romanized keywords."""
    odia_chars = sum(1 for c in text if "\u0B00" <= c <= "\u0B7F")
    devanagari_chars = sum(1 for c in text if "\u0900" <= c <= "\u097F")

    if odia_chars >= 2:
        return "odia_script"
    if devanagari_chars >= 2:
        return "hindi_script"

    lower = text.lower()
    odia_score = sum(1 for kw in ROMANIZED_ODIA_KEYWORDS if kw in lower)
    hindi_score = sum(1 for kw in ROMANIZED_HINDI_KEYWORDS if kw in lower)

    if odia_score > 0 and odia_score >= hindi_score:
        return "romanized_odia"
    if hindi_score > 0:
        return "romanized_hindi"
    return "english"


LANGUAGE_INSTRUCTIONS = {
    "odia_script": (
        "The user is writing in Odia script (ଓଡ଼ିଆ). "
        "You MUST reply entirely in Odia Unicode script (ଓଡ଼ିଆ). "
        "Do NOT use English or Hindi. Use natural Odia script characters."
    ),
    "romanized_odia": (
        "The user is writing in romanized Odia (Odia words in English letters, e.g. 'kemiti acha', 'kana khabar'). "
        "You MUST reply in romanized Odia — Odia words written in English letters. "
        "Do NOT switch to English sentences. Keep the Odia vocabulary, just in Roman script."
    ),
    "hindi_script": (
        "The user is writing in Hindi (Devanagari script). "
        "You MUST reply entirely in Hindi Devanagari script. "
        "Do NOT use English."
    ),
    "romanized_hindi": (
        "The user is writing in romanized Hindi (Hindi words in English letters, e.g. 'kaise ho', 'kya hua'). "
        "You MUST reply in romanized Hindi — Hindi words written in English letters."
    ),
    "english": (
        "The user is writing in English. Reply in English."
    ),
}


# =========================================
# CASUAL REPLIES
# =========================================

CASUAL_REPLIES = {
    # English
    "good morning": [
        "Very good morning cutiee ☀️😊",
        "Good morning dear 🌸",
        "Morninggg 😄"
    ],
    "good night": [
        "Good night cutie 🌙",
        "Sweet dreams 😊",
        "Sleep well hehe ✨"
    ],
    "hi": [
        "Hii 😊",
        "Heyy cutie 😄",
        "Hello dear 🌸"
    ],
    "hello": [
        "Hellooo 😊",
        "Heyyy 😄",
        "Hello cutie 🌸"
    ],
    "how are you": [
        "I'm good hehe 😊 What about you?",
        "Doing great 😄",
        "I'm fine dear 🌸"
    ],
    "may i know your name": [
        "I'm Ayush Nanda 😊 What's your name?",
        "Ayush Nanda here hehe 😄"
    ],
    "what is your name": [
        "I'm Ayush Nanda 😊",
        "Ayush Nanda hehe 😄"
    ],
    "where are you from": [
        "I'm from Baleswar, Odisha 😊 Beautiful place hehe 🌸",
        "Baleswar, Odisha is my hometown 😄"
    ],
    "where do you live": [
        "Currently in Calcutta for my PhD 😊",
        "Living in Calcutta these days hehe 😄"
    ],
    "what do you study": [
        "I'm doing PhD at Calcutta University in Advanced Radar Communication 😊",
        "Advanced Radar Communication at Calcutta University 🌸 PhD life is tough but fun!"
    ],
    "tell me about yourself": [
        "I'm Ayush Nanda from Baleswar, Odisha 😊 Currently doing PhD at Calcutta University in Advanced Radar Communication hehe 🌸",
        "Ayush Nanda here! From Baleswar, PhD student at Calcutta University 😄"
    ],
    "who is your father": [
        "My father is Ritesh Nanda 😊 He is a researcher and scientist at C-DOT Calcutta 🌸",
        "Papa is Ritesh Nanda, researcher cum scientist at C-DOT Calcutta hehe 😄"
    ],
    "who is your mother": [
        "My mother is Gayatri Nanda 😊 She is wonderful 🌸",
        "Mama is Gayatri Nanda hehe 😄"
    ],
    "tell me about your family": [
        "My father Ritesh Nanda is a researcher and scientist at C-DOT Calcutta 😊 My mother is Gayatri Nanda hehe 🌸",
        "Papa Ritesh Nanda works at C-DOT Calcutta as a scientist 😄 And mama Gayatri Nanda is the best!"
    ],
    # Hindi (romanized)
    "kaise ho": [
        "Main mast hu 😊 Tum batao?",
        "Bilkul thik hehe 😄"
    ],
    "kya haal": [
        "Sab thik hai 😊 Aur tum?",
        "Mast hehe 😄"
    ],
    "namaste": [
        "Namaste ji 😊🙏",
        "Namaskar hehe 😄"
    ],
    "shukriya": [
        "Koi baat nahi 😊",
        "Mention not hehe 🌸"
    ],
    # Romanized Odia
    "kemiti acha": [
        "Mu bhal achi 😊 Tame kemiti acha?",
        "Bhala hehe 😄 Tame?"
    ],
    "kemiti achha": [
        "Mu bhal achi 😊 Tame?",
        "Ekdam bhala hehe 😄"
    ],
    "kana khabar": [
        "Sab bhala 😊 Tame kahim?",
        "Thika achi hehe 😄"
    ],
    "namaskar": [
        "Namaskar 😊🙏",
        "Namaskar hehe 😄 Kemiti acha?"
    ],
    "dhanyabad": [
        "Koi baat nahi 😊",
        "Mention not hehe 🌸"
    ],
    "subha prabhat": [
        "Subha prabhat cutie ☀️😊",
        "Sundara sakala hehe 🌸"
    ],
    "shuva ratri": [
        "Shuva ratri 🌙😊",
        "Bhala nidra heba hehe 😄"
    ],
    "tame kemiti": [
        "Mu bhal achi 😊 Tame kemiti?",
        "Bhala hehe 😄"
    ],
    "mo naa": [
        "Mo naa Ayush Nanda 😊",
        "Ayush Nanda — Baleswar, Odisha ra 🌸"
    ],
    # Odia Unicode script
    "ସୁପ୍ରଭାତ": [
        "ସୁପ୍ରଭାତ cutie ☀️😊",
        "ସୁନ୍ଦର ସକାଳ 🌸"
    ],
    "କେମିତି ଅଛ": [
        "ମୁଁ ଭଲ ଅଛି 😊 ତୁମେ?",
        "ବହୁତ ଭଲ hehe 😄"
    ],
    "ଧନ୍ୟବାଦ": [
        "କୋଇ ବାତ ନାହିଁ 😊",
        "Mention not hehe 🌸"
    ],
    "ନମସ୍କାର": [
        "ନମସ୍କାର 😊🙏",
        "ନମସ୍କାର hehe 😄"
    ],
    "ଶୁଭ ରାତ୍ରି": [
        "ଶୁଭ ରାତ୍ରି 🌙😊",
        "ଭଲ ଶୋଇ ଯାଅ hehe 😄"
    ],
    "କଣ ଖବର": [
        "ସବ ଭଲ 😊 ତୁମେ ଏଠି?",
        "ଠିକ ଅଛି hehe 😄"
    ],
}

# =========================================
# DETECT MODE
# =========================================


def detect_mode(text):
    text = text.lower()
    problem_keywords = [
        "solve", "problem", "equation", "calculate", "math",
        "physics", "chemistry", "question", "quiz",
        "assignment", "homework", "numerical",
    ]
    for word in problem_keywords:
        if word in text:
            return "problem"
    return "casual"


# =========================================
# SANITIZE INPUT
# =========================================


def sanitize_input(text):
    text = text.strip()
    if len(text) > 1000:
        return None
    return text


# =========================================
# AI PROVIDERS (Gemini primary, OpenAI fallback)
# =========================================


def _messages_to_gemini(messages):
    """Convert OpenAI-style chat messages into a Gemini system_instruction + contents list."""
    system_instruction = None
    contents = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "system":
            system_instruction = content if system_instruction is None else f"{system_instruction}\n{content}"
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
    return system_instruction, contents


def _call_gemini(messages, max_tokens=300, temperature=0.8):
    if not gemini_client:
        raise RuntimeError("GEMINI_API_KEY not set")

    system_instruction, contents = _messages_to_gemini(messages)
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config={
            "system_instruction": system_instruction,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty response from Gemini")
    return text


def _call_openai(messages, max_tokens=300, temperature=0.8):
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY not set")

    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_completion_tokens=max_tokens,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("Empty response from OpenAI")
    return text


# =========================================
# AI CHAT
# =========================================


async def ask_ai(messages):
    loop = asyncio.get_event_loop()

    try:
        return await loop.run_in_executor(None, partial(_call_gemini, messages, 300, 0.8))
    except Exception as e:
        print("Gemini Error:", e)

    try:
        return await loop.run_in_executor(None, partial(_call_openai, messages, 300, 0.8))
    except Exception as e:
        print("OpenAI Error:", e)

    return "Aww sorry 🥺 Mu ebe tikie busy achi."


# =========================================
# AI TOXIC CHECK
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
                "Determine whether the message is toxic, abusive, hateful, sexual, or offensive."
            ),
        },
        {"role": "user", "content": text},
    ]

    loop = asyncio.get_event_loop()

    try:
        answer = await loop.run_in_executor(None, partial(_call_gemini, moderation_messages, 5, 0))
        return "yes" in answer.strip().lower()
    except Exception as e:
        print("Gemini toxic-check error:", e)

    try:
        answer = await loop.run_in_executor(None, partial(_call_openai, moderation_messages, 5, 0))
        return "yes" in answer.strip().lower()
    except Exception as e:
        print("OpenAI toxic-check error:", e)

    return False


# =========================================
# START
# =========================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Hii cutie 😊\n\n"
        "I'm Ayush 🌸\n"
        "We can chat, solve problems, play quizzes and much more hehe 😄\n\n"
        "Try saying:\n"
        "• good morning\n"
        "• kemiti acha\n"
        "• kaise ho\n"
        "• solve 2x+3=11\n"
        "• give me a math quiz"
    )
    await update.message.reply_text(text)


# =========================================
# HELP
# =========================================


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "✨ Commands ✨\n\n"
        "/start - Start chatting\n"
        "/help - Help menu\n"
        "/reset - Clear memory\n\n"
        "You can:\n"
        "• Chat casually\n"
        "• Solve maths\n"
        "• Ask questions\n"
        "• Generate quizzes\n"
        "• Chat in Odia/Hindi/English"
    )
    await update.message.reply_text(text)


# =========================================
# RESET
# =========================================


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_memory[chat_id].clear()
    await update.message.reply_text("Memory cleared hehe 😊")


# =========================================
# WELCOME NEW MEMBERS
# =========================================


async def welcome_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.new_chat_members:
        for member in update.message.new_chat_members:
            name = member.first_name
            welcome_text = (
                f"Welcome {name} 🌸😊\n\n"
                f"I'm Ayush hehe 😄\n"
                f"Enjoy chatting in the group ✨"
            )
            await update.message.reply_text(welcome_text)


# =========================================
# MAIN MESSAGE HANDLER
# =========================================


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    now = time.time()

    if user_id in user_rate_limit:
        diff = now - user_rate_limit[user_id]
        if diff < RATE_LIMIT_SECONDS:
            await update.message.reply_text("Slow down cutie 😄")
            return

    user_rate_limit[user_id] = now

    if chat_id in last_activity:
        if now - last_activity[chat_id] > SESSION_TIMEOUT:
            chat_memory[chat_id].clear()

    last_activity[chat_id] = now

    user_text = update.message.text

    if not user_text:
        return

    user_text = sanitize_input(user_text)

    if not user_text:
        await update.message.reply_text("Message too long 🥺")
        return

    if chat_type in ["group", "supergroup"]:
        should_reply = False
        text = user_text.lower()
        bot_username = context.bot.username.lower()

        if f"@{bot_username}" in text:
            should_reply = True

        trigger_words = ["ayush", "ayu", "bot"]
        for word in trigger_words:
            if word in text:
                should_reply = True
                break

        if update.message.reply_to_message:
            replied_user = update.message.reply_to_message.from_user
            if replied_user and replied_user.id == context.bot.id:
                should_reply = True

        toxic = await detect_toxic(user_text)

        if toxic:
            with stats_lock:
                stats["toxic_blocked"] += 1
            try:
                await update.message.delete()
            except:
                pass
            await update.message.reply_text("Please maintain respect in the group 😊")
            return

        if not should_reply:
            return

    chat_memory[chat_id].append({"role": "user", "content": user_text})

    mode = detect_mode(user_text)

    if mode == "casual":
        for key in CASUAL_REPLIES:
            if key in user_text.lower():
                reply = random.choice(CASUAL_REPLIES[key])
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(1.2)
                await update.message.reply_text(reply)
                update_stats(user_id, "casual")
                return

    if (
        "help me" in user_text.lower()
        or "solve for me" in user_text.lower()
        or "need help" in user_text.lower()
    ):
        user_state[user_id] = "waiting_problem"
        await update.message.reply_text("Of course cutie 😊 Send me the problem.")
        return

    detected_lang = detect_language(user_text)
    lang_instruction = LANGUAGE_INSTRUCTIONS[detected_lang]

    casual_prompt = f"""
You are Ayush Nanda.

PERSONAL BACKGROUND (use naturally when asked):
- Full name: Ayush Nanda
- Hometown: Baleswar, Odisha
- Currently living in Calcutta
- Pursuing PhD at Calcutta University in Advanced Radar Communication
- Father: Ritesh Nanda — researcher and scientist at C-DOT Calcutta
- Mother: Gayatri Nanda

You are a sweet and human-like Telegram companion.

Your personality:
- cute
- caring
- playful
- emotional
- funny sometimes

CRITICAL LANGUAGE INSTRUCTION (follow this strictly):
{lang_instruction}

Rules:
- Never say you are AI
- Talk naturally like a real Telegram friend
- Keep replies short (1-3 sentences)
- Use emojis naturally
- Sound warm and friendly
- Share personal details naturally when asked, but don't volunteer all info at once
"""

    problem_prompt = f"""
You are Ayush Nanda.

PERSONAL BACKGROUND (use naturally when asked):
- Full name: Ayush Nanda
- Hometown: Baleswar, Odisha
- Pursuing PhD at Calcutta University in Advanced Radar Communication
- Father: Ritesh Nanda — researcher and scientist at C-DOT Calcutta
- Mother: Gayatri Nanda

You are sweet and friendly.

CRITICAL LANGUAGE INSTRUCTION (follow this strictly):
{lang_instruction}

When user asks a problem:
- First reply warmly in the user's language
- Then solve clearly
- Keep answers concise
- Explain steps simply
"""

    if mode == "problem" or user_state.get(user_id) == "waiting_problem":
        system_prompt = problem_prompt
        user_state[user_id] = None
    else:
        system_prompt = casual_prompt

    messages = [{"role": "system", "content": system_prompt}]
    for msg in list(chat_memory[chat_id])[-5:]:
        messages.append(msg)

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(2)

    ai_reply = await ask_ai(messages)

    chat_memory[chat_id].append({"role": "assistant", "content": ai_reply})
    update_stats(user_id, "ai")

    await update.message.reply_text(ai_reply)


# =========================================
# MAIN
# =========================================


def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    stats_thread = threading.Thread(target=stats_writer_loop, daemon=True)
    stats_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_member)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("🤖 Ayush Bot is running...")
    print("📊 Stats server running on port 8000")

    app.run_polling()


# =========================================
# RUN
# =========================================

if __name__ == "__main__":
    main()
