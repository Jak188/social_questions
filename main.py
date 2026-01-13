import os
import json
import asyncio
import random
import aiosqlite
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

TOKEN = os.getenv("BOT_TOKEN", "8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE")
ADMIN_IDS = [7231324244, 8394878208]

async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
                            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, explanation TEXT)''')
        await db.commit()

# --- ጥያቄዎችን ከ JSON ማንበቢያ ---
def load_questions(subject_name):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_questions = json.load(f)
            # በተሰጠው subject መሰረት ጥያቄዎችን ለይቶ ያወጣል
            return [q for q in all_questions if q['subject'] == subject_name]
    except Exception as e:
        print(f"JSON Error: {e}")
        return []

async def is_muted(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                until = datetime.fromisoformat(row[0])
                if datetime.now() < until: return True
    return False

async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    subject = context.job.data['subject']
    chat_id = context.job.chat_id
    questions = load_questions(subject)
    
    if not questions: return

    q = random.choice(questions)
    message = await context.bot.send_poll(
        chat_id, q['q'], q['o'], is_anonymous=False, 
        type=Poll.QUIZ, correct_option_id=q['c'], explanation=q['exp']
    )
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, ?)", (message.poll.id, q['c'], chat_id, q['exp']))
        await db.commit()

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    if await is_muted(user_id): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if poll_data and ans.option_ids[0] == poll_data[0]:
        user_name = ans.user.first_name
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, user_name))
            await db.execute("UPDATE users SET points = points + 8 WHERE user_id = ?", (user_id,))
            await db.commit()

async def start_quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    # Command: /History_srm -> Subject: History
    subject = update.message.text.split('_')[0][1:]
    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=update.effective_chat.id, 
                                    data={'subject': subject}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🚀 የ {subject} ውድድር ተጀመረ!")

# ... (rank2, mute, un_mute commands are the same as before) ...

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler(["History_srm", "Geography_srm", "Mathematics_srm", "English_srm", "General_srm"], start_quiz_cmd))
    application.add_handler(CommandHandler("mute", lambda u, c: None)) # Add Mute/Unmute logic here
    application.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
