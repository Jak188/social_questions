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

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN", "8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE")
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE SETUP ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
                            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, explanation TEXT)''')
        await db.commit()

# --- JSON LOAD ---
def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"JSON Error: {e}")
        return {}

# --- HELPERS ---
async def is_muted(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                until = datetime.fromisoformat(row[0])
                if datetime.now() < until: return True
    return False

# --- QUIZ LOGIC ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    subject = context.job.data['subject']
    chat_id = context.job.chat_id
    questions = load_questions()
    
    if subject not in questions or not questions[subject]:
        await context.bot.send_message(chat_id, f"⚠️ የ {subject} ጥያቄዎች በፋይሉ ውስጥ አልተገኙም!")
        return

    q = random.choice(questions[subject])
    message = await context.bot.send_poll(
        chat_id, q['q'], q['o'], is_anonymous=False, 
        type=Poll.QUIZ, correct_option_id=q['c'], explanation=q['e']
    )
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, ?)", (message.poll.id, q['c'], chat_id, q['e']))
        await db.commit()

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    if await is_muted(ans.user_id): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if poll_data and ans.option_ids[0] == poll_data[0]:
        user_name = update.effective_user.first_name if update.effective_user else "ተሳታፊ"
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (ans.user_id, user_name))
            await db.execute("UPDATE users SET points = points + 8 WHERE user_id = ?", (ans.user_id,))
            await db.commit()

# --- ADMIN COMMANDS ---
async def start_quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split('_')[0][1:]
    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=update.effective_chat.id, data={'subject': cmd}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🚀 የ {cmd} ውድድር ተጀመረ!")

async def stop2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for job in jobs: job.schedule_removal()
    await update.message.reply_text("🏁 ውድድሩ ቆሟል።")

async def mute_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS or not update.message.reply_to_message: return
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    target = update.message.reply_to_message.from_user
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (target.id, target.first_name))
        await db.execute("UPDATE users SET muted_until = ? WHERE user_id = ?", (until, target.id))
        await db.commit()
    await update.message.reply_text(f"🚫 {target.first_name} ለ 17 ደቂቃ ታግዷል።")

async def un_mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS or not update.message.reply_to_message: return
    target = update.message.reply_to_message.from_user
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target.id,))
        await db.commit()
    await update.message.reply_text(f"✅ {target.first_name} እገዳው ተነስቷል።")

async def rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    text = "🏆 **ደረጃ (Rank):**\n"
    for i, r in enumerate(rows): text += f"{i+1}. {r[0]}: {r[1]} ነጥብ\n"
    await update.message.reply_text(text)

async def clear_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ነጥብ በሙሉ ተሰርዟል።")

# --- MAIN ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler(["History_srm", "Geography_srm", "Mathematics_srm", "English_srm"], start_quiz_cmd))
    application.add_handler(CommandHandler("stop2", stop2))
    application.add_handler(CommandHandler("rank2", rank2))
    application.add_handler(CommandHandler("clear_rank", clear_rank))
    application.add_handler(CommandHandler("un_mute", un_mute_cmd))
    # ማሳሰቢያ፡ Mute ለማድረግ በቀጥታ Mute የሚል ኮማንድ የለህም፣ ነገር ግን /un_mute ጋር ተመሳሳይ በሆነ መንገድ /mute የሚል ብትጨምር ይሻላል
    
    application.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
