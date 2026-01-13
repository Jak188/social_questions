import os
import json
import asyncio
import random
import aiosqlite
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters

# --- Uptime Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN", "8256328585:AAHTvHxxChdIohofHdDcrOeTN1iEbWcx9QI")
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- HELPERS ---
def load_questions(subject):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            return [q for q in all_q if q.get('subject') == subject]
    except: return []

# --- QUIZ LOGIC ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    subject = context.job.data['subject']
    questions = load_questions(subject)
    if not questions: return
    q = random.choice(questions)
    msg = await context.bot.send_poll(
        context.job.chat_id, q['q'], q['o'], is_anonymous=False, 
        type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
    )
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], context.job.chat_id))
        await db.commit()

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] and datetime.now() < datetime.fromisoformat(row[0]): return

        async with db.execute("SELECT correct_option, first_done FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done = poll_data
    points = 0
    if ans.option_ids[0] == correct_idx:
        if first_done == 0:
            points = 8
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
                await db.commit()
        else: points = 4
    else: points = 1.5

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, ans.user.first_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMANDS ---
async def start2_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        await update.message.reply_text("ሰላም አድሚን! አንተ መመዝገብ አያስፈልግህም።")
        return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.first_name))
        await db.commit()
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"👤 አዲስ ምዝገባ:\nስም: {user.first_name}\nID: `{user.id}`\nለማጽደቅ: `/approve {user.id}`")
    await update.message.reply_text("ጥያቄህ ለአድሚን ተልኳል፤ ሲፈቀድልህ ቦቱን በግል መጠቀም ትችላለህ።")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = context.args[0]
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
        await update.message.reply_text(f"✅ ተጠቃሚ {target_id} ጸድቋል።")
    except: await update.message.reply_text("ID ቁጥሩን በትክክል ያስገቡ።")

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    # Rule 7-10: የትምህርት አይነቶች (SRM2/SRM)
    text = update.message.text.split('@')[0]
    subject = text.split('_')[0][1:].capitalize()
    context.job_queue.run_repeating(send_quiz, 240, 1, update.effective_chat.id, {'subject': subject}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🚀 የ {subject} ውድድር በየ 4 ደቂቃው ተጀመረ!")

async def stop2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for job in jobs: job.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "🏁 ውድድሩ ቆሟል!\n🏆 ደረጃ:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def handle_violation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 14: አድሚን ያልሆነ ሰው አድሚን ትዕዛዝ ሲነካ
    user = update.effective_user
    if user.id in ADMIN_IDS: return
    
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user.id))
        await db.commit()
    await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደሃል!")

async def private_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 12: በግል ቦቱን ለማውራት ምዝገባ ይፈትሻል
    user = update.effective_user
    if user.id in ADMIN_IDS: return # አድሚን አይታገድም
    
    if update.effective_chat.type == "private":
        async with aiosqlite.connect('quiz_bot.db') as db:
            async with db.execute("SELECT status FROM users WHERE user_id = ?", (user.id,)) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] != 'approved':
                    await update.message.reply_text("⚠️ ቦቱን በግል ለማውራት መጀመሪያ መመዝገብ አለብህ። እባክህ /start2 በል።")
                    return

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start2", start2_registration))
    app_bot.add_handler(CommandHandler("approve", approve))
    app_bot.add_handler(CommandHandler(["History_srm2", "Geography_srm2", "Mathematics_srm2", "English_srm"], start_quiz))
    app_bot.add_handler(CommandHandler("stop2", stop2))
    app_bot.add_handler(CommandHandler("rank2", lambda u, c: stop2(u, c)))
    app_bot.add_handler(CommandHandler("mute2", lambda u, c: None)) # Mute logic code here
    
    # አድሚን ያልሆኑ ሰዎችን የሚቀጣ (Rule 14)
    app_bot.add_handler(MessageHandler(filters.Regex(r'^\/.*2$') & ~filters.User(ADMIN_IDS), handle_violation))
    
    # በግል ሲያወሩ ምዝገባ የሚፈትሽ (Rule 12)
    app_bot.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.User(ADMIN_IDS), private_check))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
