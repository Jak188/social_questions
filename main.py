import os
import json
import asyncio
import random
import aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters

# --- 1. Flask Server (Keep Alive) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USER = "@penguiner"
global_pause = False

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0,
             correct_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject: return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except: return []

async def get_user_data(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Quiz Logic (Scoring Adjusted to +1.5 for Wrong) ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if global_pause: return
    job = context.job
    subject = job.data.get('subject')
    questions = load_questions(subject)
    if not questions: return

    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            job.chat_id, f"[{q.get('subject', 'ጠቅላላ')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c'])
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, int(q['c']), job.chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    u_id = ans.user.id
    user = await get_user_data(u_id)
    
    if not user or user[5] == 1 or user[3] != 'approved' or global_pause: return 
    if user[4] and datetime.now(timezone.utc) < datetime.fromisoformat(user[4]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    if not poll_data: return

    is_correct = (ans.option_ids[0] == poll_data[0])
    # የነጥብ ህግ: ትክክል 1ኛ (8), ትክክል ሌሎች (4), ስህተት (1.5)
    points = 8 if (is_correct and poll_data[1] == 0) else (4 if is_correct else 1.5)

    async with aiosqlite.connect('quiz_bot.db') as db:
        col = "correct_count" if is_correct else "wrong_count"
        await db.execute(f"UPDATE users SET points = points + ?, {col} = {col} + 1 WHERE user_id = ?", (points, u_id))
        if is_correct and poll_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
        await db.commit()

# --- 6. Protection & Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    u_data = await get_user_data(user.id)

    if chat_type == "private":
        if not u_data:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
                await db.commit()
            await update.message.reply_text(f"👋 ሰላም {user.first_name}!\nምዝገባው ላይ ነኝ፤ አድሚኑ ቢዚ ስለሆነ በትዕግስት ይጠብቁ።")
            for admin in ADMIN_IDS:
                await context.bot.send_message(admin, f"🔔 አዲስ ተመዝጋቢ: {user.first_name} ({user.id})\nማጽደቅ: `/approve {user.id}`")
            return
        
        valid_cmds = ['/start', '/rank2', '/info2', '/keep']
        if update.message.text.split()[0] not in valid_cmds and user.id not in ADMIN_IDS:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"⚠️ የህግ ጥሰት! ያለ ፈቃድ ትዕዛዝ በመጠቀሞ ታግደዋል። {ADMIN_USER} ን ያነጋግሩ።")
            return

    if chat_type != "private" and user.id not in ADMIN_IDS:
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} ያለ አድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።", reply_to_message_id=update.message.message_id)
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subs = {'history_srm2':'history', 'geography_srm2':'geography', 'mathematics_srm2':'mathematics', 'english_srm2':'english', 'start2':None}
    if cmd in subs or cmd == "start2":
        subject = subs.get(cmd)
        jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
        for j in jobs: j.schedule_removal()
        context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=update.effective_chat.id, data={'subject': subject}, name=str(update.effective_chat.id))
        await update.message.reply_text(f"🚀 የ{subject if subject else 'ጠቅላላ'} ውድድር ተጀመረ! (በየ 4 ደቂቃ)")

# --- 7. Admin Commands ---
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            if cmd == "approve":
                await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (tid,))
                await context.bot.send_message(tid, "🎉 ምዝገባዎ ጸድቋል!")
            elif cmd == "anapprove":
                await context.bot.send_message(tid, "❌ ጥያቄዎ ውድቅ ተደርጓል።")
            elif cmd == "block":
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (tid,))
            elif cmd == "unmute":
                await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (tid,))
            elif cmd == "close":
                jobs = context.job_queue.get_jobs_by_name(str(tid))
                for j in jobs: j.schedule_removal()
            await db.commit()
            await update.message.reply_text("✅ ተፈጽሟል።")
    except: pass

async def appt_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    global global_pause
    cmd = update.message.text.split()[0][1:].lower()
    global_pause = (cmd == "appt")
    status = "ቆሟል" if global_pause else "ቀጥሏል"
    await update.message.reply_text(f"📢 ቦቱ ከአድሚን በመጣ ትዕዛዝ {status}። {ADMIN_USER}")

# --- 8. Main ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler(["start", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "start2", "keep"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "unmute", "close"], admin_cmd))
    app_bot.add_handler(CommandHandler(["appt", "apptt"], appt_logic))
    app_bot.add_handler(CommandHandler("rank2", lambda u,c: asyncio.create_task(rank2_cmd(u,c))))
    app_bot.add_handler(CommandHandler("stop2", lambda u,c: [j.schedule_removal() for j in c.job_queue.get_jobs_by_name(str(u.effective_chat.id))] or u.message.reply_text("🛑 ቆሟል።")))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling(drop_pending_updates=True)

async def rank2_cmd(update, context):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
            rows = await c.fetchall()
    res = "🏆 ምርጥ 15:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

if __name__ == '__main__':
    main()
