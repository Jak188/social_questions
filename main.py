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

# --- 1. Flask Server (For Render Uptime) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 
bot_active_sessions = {}

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0, reg_date TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, username TEXT, action TEXT, timestamp TEXT)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        if not os.path.exists('questions.json'): return []
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject:
                return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except Exception: return []

async def get_user_data(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT points, muted_until, is_blocked, status, username, reg_date FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Quiz Logic ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    chat_id = job.chat_id
    subject = job.data.get('subject')
    questions = load_questions(subject)
    
    if not questions: return

    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            chat_id, f"[{q.get('subject', 'Random')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id, first_done) VALUES (?, ?, ?, 0)", 
                             (msg.poll.id, int(q['c']), chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user = await get_user_data(user_id)
    
    if not user or user[2] == 1 or user[3] != 'approved': return 
    if user[1] and datetime.now(timezone.utc) < datetime.fromisoformat(user[1]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done, chat_id = poll_data
    is_correct = ans.option_ids[0] == correct_idx
    
    points = 8 if (is_correct and first_done == 0) else (4 if is_correct else 1.5)
    action_mark = "✅" if is_correct else "❌"

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.execute("INSERT INTO logs (user_id, username, action, timestamp) VALUES (?, ?, ?, ?)", 
                         (user_id, ans.user.first_name, action_mark, datetime.now().strftime("%H:%M:%S")))
        await db.commit()

# --- 6. Admin & Command Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_data = await get_user_data(user.id)

    if not user_data:
        reg_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_date) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, reg_time))
            await db.commit()
        
        welcome = (f"👋 ሰላም {user.first_name}!\nየምዝገባ ጥያቄዎ በሂደት ላይ ነው። "
                   f"አድሚኑ ቢዚ ስለሆነ እባክዎ በትዕግስት ይጠብቁ። "
                   f"ጥያቄዎ ተቀባይነት ሲያገኝ የማረጋገጫ መልእክት ይደርስዎታል።\n\nለበለጠ መረጃ፡ {ADMIN_USERNAME}")
        await update.message.reply_text(welcome)
        return

    if user_data[3] == 'pending':
        await update.message.reply_text("⏳ ጥያቄዎ ገና አልጸደቀም። እባክዎ በትዕግስት ይጠብቁ።")
        return

    if user.id not in ADMIN_IDS and update.effective_chat.type != "private":
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text("⚠️ የአድሚን ትዕዛዝ ስለነኩ ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2": "history", "geography_srm2": "geography", "mathematics_srm2": "mathematics", "english_srm2": "english"}
    subject = subject_map.get(cmd)

    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    bot_active_sessions[chat_id] = f"📍 {update.effective_chat.title or 'Private'} | 👤 {user.first_name}"
    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀምሯል!")

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    global GLOBAL_STOP

    try:
        if cmd == "appt":
            GLOBAL_STOP = True
            await update.message.reply_text("🛑 ቦቱ ለሁሉም ተጠቃሚዎች ቆሟል።")
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT user_id FROM users") as cursor:
                    users = await cursor.fetchall()
            for u in users:
                try: await context.bot.send_message(u[0], f"🛑 ቦቱ ከአድሚን በመጣ ትዕዛዝ ቆሟል። {ADMIN_USERNAME}")
                except: continue

        elif cmd == "apptt":
            GLOBAL_STOP = False
            await update.message.reply_text("✅ ቦቱ ወደ ስራ ተመልሷል።")
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT user_id FROM users") as cursor:
                    users = await cursor.fetchall()
            for u in users:
                try: await context.bot.send_message(u[0], "✅ ቦቱ አሁን ወደ ስራ ተመልሷል። መሳተፍ ትችላላችሁ!")
                except: continue

        elif cmd == "keep2":
            if not bot_active_sessions: return await update.message.reply_text("📴 ምንም ክፍት ሰሲሽን የለም።")
            for cid, info in bot_active_sessions.items():
                await update.message.reply_text(f"{info}\nID: `{cid}`\n\nይህንን ሪፕላይ በማድረግ /close2 ይበሉ")

        elif cmd == "close2":
            if update.message.reply_to_message:
                target_id = int(update.message.reply_to_message.text.split("ID: `")[1].split("`")[0])
                jobs = context.job_queue.get_jobs_by_name(str(target_id))
                for j in jobs: j.schedule_removal()
                if target_id in bot_active_sessions: del bot_active_sessions[target_id]
                await update.message.reply_text(f"🏁 ሰሲሽን {target_id} ቆሟል።")
                await context.bot.send_message(target_id, "🏁 ቦቱ በአድሚን ትዕዛዝ ቆሟል።")

        elif cmd == "log":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT username, action, timestamp FROM logs ORDER BY rowid DESC LIMIT 20") as cursor:
                    rows = await cursor.fetchall()
            res = "📜 Log:\n" + "\n".join([f"{r[2]} | {r[0]}: {r[1]}" for r in rows]) if rows else "ምንም ሎግ የለም"
            await update.message.reply_text(res)

        elif cmd == "block":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (uid,))
                await db.commit()
            await update.message.reply_text(f"🚫 {uid} ታግዷል።")

        elif cmd == "unblock":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 0, muted_until = NULL WHERE user_id = ?", (uid,))
                await db.commit()
            await update.message.reply_text(f"✅ {uid} እገዳ ተነስቷል።")

        elif cmd == "approve":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
            await update.message.reply_text(f"✅ {uid} ጸድቋል።")

    except Exception as e: await update.message.reply_text(f"⚠️ ስህተት፡ {e}")

# --- 7. Main ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["appt", "apptt", "keep2", "close2", "log", "block", "unblock", "approve", "info2"], admin_actions))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
