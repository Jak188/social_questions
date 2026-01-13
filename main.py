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

# --- Flask Server (Uptime) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIG ---
TOKEN = "8256328585:AAHTvHxxChdIohofHdDcrOeTN1iEbWcx9QI"
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE SETUP ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
                             is_blocked INTEGER DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
                            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, 
                             first_winner INTEGER DEFAULT 0)''')
        await db.commit()

# --- HELPERS ---
def load_questions(subject_name):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            return [q for q in all_q if q.get('subject') == subject_name]
    except: return []

# --- QUIZ LOGIC ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    subject = context.job.data['subject']
    questions = load_questions(subject)
    if not questions: return
    
    q = random.choice(questions)
    message = await context.bot.send_poll(
        context.job.chat_id, q['q'], q['o'], is_anonymous=False, 
        type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
    )
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (?, ?, ?)", 
                         (message.poll.id, q['c'], context.job.chat_id))
        await db.commit()

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user_name = ans.user.first_name

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_data = await cursor.fetchone()
            if user_data and user_data[0] == 1: return

        async with db.execute("SELECT correct_option, first_winner FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_info = await cursor.fetchone()
    
    if not poll_info: return
    correct_opt = poll_info[0]
    has_first_winner = poll_info[1]
    
    points_to_add = 0
    if ans.option_ids[0] == correct_opt:
        if has_first_winner == 0:
            points_to_add = 8  # Rule 1: ቀድሞ ለመለሰ 8 ነጥብ
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_winner = 1 WHERE poll_id = ?", (ans.poll_id,))
                await db.commit()
        else:
            points_to_add = 4  # Rule 2: ዘግይቶ ለመለሰ 4 ነጥብ
    else:
        points_to_add = 1.5 # Rule 3: ለተሳሳተ 1.5 ነጥብ

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, user_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points_to_add, user_id))
        await db.commit()

# --- COMMANDS ---
async def start_quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    subject = update.message.text.split('_')[0][1:]
    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=update.effective_chat.id, data={'subject': subject})
    await update.message.reply_text(f"🚀 የ {subject} ውድድር ተጀመረ (በየ 4 ደቂቃው)!")

# Rule 7: ማቆሚያ ኮማንድ ወደ /stop2 ተቀይሯል
async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    
    # ሁሉንም ንቁ ጥያቄዎች ያቆማል
    jobs = context.job_queue.jobs()
    if not jobs:
        await update.message.reply_text("⚠️ በአሁኑ ሰዓት የሚሄድ ውድድር የለም።")
        return

    for job in jobs:
        job.schedule_removal()
    
    # ውጤቱን ያሳያል
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    
    rank_text = "🏁 ውድድሩ በ /stop2 ትእዛዝ ተጠናቋል!\n🏆 የደረጃ ሰንጠረዥ (Top 10):\n"
    for i, r in enumerate(rows):
        rank_text += f"{i+1}. {r[0]}: {r[1]} ነጥብ\n"
    
    await update.message.reply_text(rank_text)

async def clear_rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ነጥቦች በሙሉ ተሰርዘዋል።")

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler(["History_srm", "Geography_srm", "Mathematics_srm", "English_srm"], start_quiz_cmd))
    application.add_handler(CommandHandler("stop2", stop2_cmd)) # ኮማንዱ እዚህ ተቀይሯል
    application.add_handler(CommandHandler("clear_rank2", clear_rank2))
    application.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
