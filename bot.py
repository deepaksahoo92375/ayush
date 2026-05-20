import os
import time
import random
import asyncio

from collections import defaultdict, deque
from dotenv import load_dotenv
from groq import Groq

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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = Groq(api_key=OPENAI_API_KEY)

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
# CASUAL REPLIES
# =========================================

CASUAL_REPLIES = {
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
        "I'm Ayush 😊 What's your name?",
        "Ayush here hehe 😄"
    ],

    "where are you from": [
        "I'm from your chatbox 😄",
        "Somewhere inside Telegram hehe 🌸"
    ],

    # Hindi
    "kaise ho": [
        "Main mast hu 😊 Tum batao?",
        "Bilkul thik hehe 😄"
    ],

    # Odia
    "kemiti acha": [
        "Mu bhal achi 😊 Tame?",
        "Bhala hehe 😄"
    ],

    "ସୁପ୍ରଭାତ": [
        "ସୁପ୍ରଭାତ cutie ☀️😊",
        "ସକାଳର ଶୁଭେଚ୍ଛା 🌸"
    ],

    "କେମିତି ଅଛ": [
        "ମୁଁ ଭଲ ଅଛି 😊",
        "ବହୁତ ଭଲ hehe 😄"
    ]
}

# =========================================
# DETECT MODE
# =========================================

def detect_mode(text):

    text = text.lower()

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
# AI CHAT
# =========================================

async def ask_ai(messages):

    try:

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.8,
            max_tokens=300,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:

        print("AI Error:", e)

        return "Aww sorry 🥺 Mu ebe tikie busy achi."

# =========================================
# AI TOXIC CHECK
# =========================================

async def detect_toxic(text):

    text = text.lower()

    # Local filter
    for word in TOXIC_WORDS:

        if word in text:
            return True

    # AI moderation
    try:

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Reply ONLY with YES or NO. "
                        "Determine whether the message is toxic, abusive, hateful, sexual, or offensive."
                    )
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            temperature=0,
            max_tokens=5
        )

        answer = response.choices[0].message.content.strip().lower()

        return "yes" in answer

    except:
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

    await update.message.reply_text(
        "Memory cleared hehe 😊"
    )

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

    # =====================================
    # RATE LIMIT
    # =====================================

    if user_id in user_rate_limit:

        diff = now - user_rate_limit[user_id]

        if diff < RATE_LIMIT_SECONDS:

            await update.message.reply_text(
                "Slow down cutie 😄"
            )

            return

    user_rate_limit[user_id] = now

    # =====================================
    # SESSION RESET
    # =====================================

    if chat_id in last_activity:

        if now - last_activity[chat_id] > SESSION_TIMEOUT:
            chat_memory[chat_id].clear()

    last_activity[chat_id] = now

    # =====================================
    # USER TEXT
    # =====================================

    user_text = update.message.text

    if not user_text:
        return

    user_text = sanitize_input(user_text)

    if not user_text:

        await update.message.reply_text(
            "Message too long 🥺"
        )

        return

    # =====================================
    # GROUP CONTROL
    # =====================================

    if chat_type in ["group", "supergroup"]:

        should_reply = False

        text = user_text.lower()

        # Mention username
        bot_username = context.bot.username.lower()

        if f"@{bot_username}" in text:
            should_reply = True

        # Trigger words
        trigger_words = [
            "ayush",
            "ayu",
            "bot",
        ]

        for word in trigger_words:

            if word in text:
                should_reply = True
                break

        # Reply to bot
        if update.message.reply_to_message:

            replied_user = update.message.reply_to_message.from_user

            if replied_user:

                if replied_user.id == context.bot.id:
                    should_reply = True

        # Toxic moderation
        toxic = await detect_toxic(user_text)

        if toxic:

            try:
                await update.message.delete()
            except:
                pass

            await update.message.reply_text(
                "Please maintain respect in the group 😊"
            )

            return

        # Ignore unrelated messages
        if not should_reply:
            return

    # =====================================
    # SAVE MEMORY
    # =====================================

    chat_memory[chat_id].append({
        "role": "user",
        "content": user_text
    })

    # =====================================
    # DETECT MODE
    # =====================================

    mode = detect_mode(user_text)

    # =====================================
    # FAST CASUAL REPLIES
    # =====================================

    if mode == "casual":

        for key in CASUAL_REPLIES:

            if key in user_text.lower():

                reply = random.choice(
                    CASUAL_REPLIES[key]
                )

                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action=ChatAction.TYPING
                )

                await asyncio.sleep(1.2)

                await update.message.reply_text(reply)

                return

    # =====================================
    # WAITING FOR PROBLEM
    # =====================================

    if (
        "help me" in user_text.lower()
        or "solve for me" in user_text.lower()
        or "need help" in user_text.lower()
    ):

        user_state[user_id] = "waiting_problem"

        await update.message.reply_text(
            "Of course cutie 😊 Send me the problem."
        )

        return

    # =====================================
    # SYSTEM PROMPTS
    # =====================================

    casual_prompt = """
You are Ayush.

You are a sweet and human-like Telegram companion.

Your personality:
- cute
- caring
- playful
- emotional
- funny sometimes

IMPORTANT LANGUAGE RULE:
- Always reply in the SAME language as the user.
- If user speaks Odia, reply in Odia.
- If user speaks Hindi, reply in Hindi.
- If user speaks English, reply in English.
- If user mixes languages, reply naturally in mixed language too.

Rules:
- Never say you are AI
- Talk naturally like a real Telegram friend
- Keep replies short
- Use emojis naturally
- Sound warm and friendly
"""

    problem_prompt = """
You are Ayush.

You are sweet and friendly.

IMPORTANT:
- Reply in the SAME language used by the user.
- If user uses Odia, explain in Odia.
- If user uses Hindi, explain in Hindi.
- If user uses English, explain in English.

When user asks a problem:
- First reply warmly
- Then solve clearly
- Keep answers concise
- Explain steps simply

Example:
'Sure cutie 😊 here's the answer...'
"""

    # =====================================
    # SELECT PROMPT
    # =====================================

    if (
        mode == "problem"
        or user_state.get(user_id) == "waiting_problem"
    ):

        system_prompt = problem_prompt

        user_state[user_id] = None

    else:

        system_prompt = casual_prompt

    # =====================================
    # BUILD AI MESSAGES
    # =====================================

    messages = [{
        "role": "system",
        "content": system_prompt
    }]

    for msg in list(chat_memory[chat_id])[-5:]:

        messages.append(msg)

    # =====================================
    # TYPING EFFECT
    # =====================================

    await context.bot.send_chat_action(
        chat_id=chat_id,
        action=ChatAction.TYPING
    )

    await asyncio.sleep(2)

    # =====================================
    # AI RESPONSE
    # =====================================

    ai_reply = await ask_ai(messages)

    # =====================================
    # SAVE AI RESPONSE
    # =====================================

    chat_memory[chat_id].append({
        "role": "assistant",
        "content": ai_reply
    })

    # =====================================
    # SEND REPLY
    # =====================================

    await update.message.reply_text(ai_reply)

# =========================================
# MAIN
# =========================================

def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset))

    # Welcome new members
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome_member
        )
    )

    # Text messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("🤖 Ayush Bot is running...")

    app.run_polling()

# =========================================
# RUN
# =========================================

if __name__ == "__main__":
    main()