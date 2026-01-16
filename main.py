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

# --- 1. Flask Server ---
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
bot_active_sessions = {} # ክፍት የሆኑ ቦታዎችን ለመያዝ

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
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, int(q['c']), chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user = await get_user_data(user_id)
    
    # ጸድቆ ካልሆነ ነጥብ አይመዘገብም
    if not user or user[2] == 1 or user[3] != 'approved': return 

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

# --- 6. Command Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_data = await get_user_data(user.id)

    if not user_data:
        reg_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_date) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, reg_time))
            await db.commit()
        
        welcome_msg = (
            f"👋 ሰላም {user.first_name}!\n\n"
            f"የምዝገባ ጥያቄዎ በሂደት ላይ ነው። ጥያቄዎ ተቀባይነት ሲያገኝ የማረጋገጫ መልእክት ይደርስዎታል። "
            f"አድሚኑ ቢዚ ስለሆነ እባክዎ በትዕግስት ይጠብቁ። ማረጋገጫ ሲያገኙ እናሳውቅዎታለን።\n\n"
            f"ለበለጠ መረጃ፡ {ADMIN_USERNAME} ን ያነጋግሩ።"
        )
        await update.message.reply_text(welcome_msg)
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ምዝገባ፡ {user.first_name}\nID: `{user.id}`", parse_mode='Markdown')
        return

    if user_data[3] == 'pending':
        await update.message.reply_text(f"⏳ ጥያቄዎ ገና አልጸደቀም። አድሚኑ ቢዚ ስለሆነ እባክዎ በትዕግስት ይጠብቁ። {ADMIN_USERNAME}")
        return

    # ውድድር ማስጀመሪያ
    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2": "history", "geography_srm2": "geography", "mathematics_srm2": "mathematics", "english_srm2": "english"}
    subject = subject_map.get(cmd)

    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    
    # ሰሲሽን መመዝገብ
    bot_active_sessions[chat_id] = f"📍 {update.effective_chat.title or 'Private'} | 👤 {user.first_name}"
    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀምሯል!")

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    
    if cmd == "keep2":
        if not bot_active_sessions:
            await update.message.reply_text("📴 ምንም ክፍት ሰሲሽን የለም።")
            return
        for cid, info in bot_active_sessions.items():
            await update.message.reply_text(f"{info}\nID: `{cid}`\n\nይህንን ሪፕላይ በማድረግ /close2 ይበሉ", parse_mode='Markdown')

    elif cmd == "close2":
        if update.message.reply_to_message:
            try:
                # ከሪፕላይ መልእክቱ ID መፈለግ
                text = update.message.reply_to_message.text
                target_id = text.split("ID: ")[1].split("\n")[0].strip("`")
                jobs = context.job_queue.get_jobs_by_name(target_id)
                for j in jobs: j.schedule_removal()
                if int(target_id) in bot_active_sessions:
                    del bot_active_sessions[int(target_id)]
                await update.message.reply_text(f"🏁 ሰሲሽን {target_id} ቆሟል።")
                await context.bot.send_message(target_id, f"🏁 ቦቱ በአድሚን ትዕዛዝ ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")
            except:
                await update.message.reply_text("❌ ስህተት! መልእክቱን በትክክል ሪፕላይ ያድርጉ።")

    elif cmd == "log":
        async with aiosqlite.connect('quiz_bot.db') as db:
            async with db.execute("SELECT username, action, timestamp FROM logs ORDER BY rowid DESC LIMIT 20") as cursor:
                rows = await cursor.fetchall()
        if not rows:
            await update.message.reply_text("📜 ምንም ሎግ የለም።")
            return
        res = "📜 የውድድር ዝርዝር (Log):\n\n" + "\n".join([f"{r[2]} | {r[0]}: {r[1]}" for r in rows])
        await update.message.reply_text(res)

    elif cmd == "info2":
        async with aiosqlite.connect('quiz_bot.db') as db:
            async with db.execute("SELECT username, user_id, reg_date, status FROM users") as cursor:
                rows = await cursor.fetchall()
        res = "👥 ተመዝጋቢዎች:\n\n"
        for r in rows: res += f"👤 {r[0]}\nID: `{r[1]}`\n📅 መቼ: {r[2]} | {r[3]}\n\n"
        await update.message.reply_text(res, parse_mode='Markdown')

    elif cmd == "approve":
        uid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
        await context.bot.send_message(uid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል፤ አሁን መወዳደር ይችላሉ።")
        await update.message.reply_text(f"✅ ተጠቃሚ {uid} ጸድቋል።")

# --- 7. Main ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler(["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["keep2", "close2", "log", "info2", "approve"], admin_actions))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
