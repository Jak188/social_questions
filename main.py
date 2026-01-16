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
bot_start_info = {} # ቦቱ የትና መቼ እንደተከፈተ መረጃ መያዣ

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

    if is_correct and first_done == 0:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
            await db.commit()
        await context.bot.send_message(chat_id, f"🏆 እንኳን ደስ አለዎት {ans.user.first_name}! ቀድመው በመመለስዎ 8 ነጥብ አግኝተዋል።")

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?)", (user_id, ans.user.first_name, action_mark, datetime.now().strftime("%Y-%m-%d %H:%M")))
        await db.commit()

# --- 6. Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user_data = await get_user_data(user.id)

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"🚫 ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
        return

    if not user_data:
        reg_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_date) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, reg_time))
            await db.commit()
        await update.message.reply_text(f"👋 ሰላም {user.first_name}!\nየምዝገባ ጥያቄዎ ደርሶናል። አድሚን እስኪያጸድቅ ድረስ ስራ ስለሚበዛብን በትዕግስት ይጠብቁ።")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ተመዝጋቢ: {user.first_name}\nID: `{user.id}`\nሰዓት: {reg_time}", parse_mode='Markdown')
        return
    
    if user_data[2] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
        return

    if user.id not in ADMIN_IDS and chat_type != "private":
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶብዎታል፤ ለ 17 ደቂቃም ታግደዋል።")
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2": "history", "geography_srm2": "geography", "mathematics_srm2": "mathematics", "english_srm2": "english"}
    subject = subject_map.get(cmd)

    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    
    # የት እንደተከፈተ መረጃ መመዝገብ
    bot_start_info[chat_id] = {
        "user": user.first_name,
        "type": chat_type,
        "title": update.effective_chat.title or "Private",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀምሯል!")

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await update.message.reply_text("📊 እስካሁን ምንም ነጥብ አልተመዘገበም።")
        return
    res = "📊 ወቅታዊ የደረጃ ሰንጠረዥ (Top 15):\n" + "\n".join([f"{i+1}. {r[0]} ➔ {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    
    try:
        if cmd == "keep2":
            if not bot_start_info:
                await update.message.reply_text("📴 በአሁኑ ሰዓት በየትኛውም ቦታ ክፍት አይደለም።")
                return
            res = "🟢 ቦቱ ክፍት የሆኑባቸው ቦታዎች:\n\n"
            for cid, info in bot_start_info.items():
                res += f"📍 ቦታ: {info['title']} ({info['type']})\n👤 የከፈተው: {info['user']}\n⏰ ሰዓት: {info['time']}\n\n"
            await update.message.reply_text(res)

        elif cmd == "info2":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT username, user_id, reg_date, status FROM users") as cursor:
                    rows = await cursor.fetchall()
            res = f"👥 ጠቅላላ ተመዝጋቢዎች: {len(rows)}\n\n"
            for r in rows:
                res += f"👤 {r[0]} | ID: `{r[1]}`\n📅 መቼ: {r[2]} | {r[3]}\n\n"
            await update.message.reply_text(res, parse_mode='Markdown')

        elif cmd == "log":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT username, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 20") as cursor:
                    rows = await cursor.fetchall()
            res = "📜 የውድድር ዝርዝር (Log):\n" + "\n".join([f"{r[2]} | {r[0]}: {r[1]}" for r in rows])
            await update.message.reply_text(res)

        elif cmd == "approve":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
            await update.message.reply_text(f"✅ ተጠቃሚ {uid} ጸድቋል።")

        elif cmd == "block":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
            await update.message.reply_text(f"🚫 {uid} ታግዷል።")

        elif cmd == "clear_rank2":
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = 0")
                await db.commit()
            await update.message.reply_text("🧹 ሁሉም ነጥቦች ተሰርዘዋል።")

    except: await update.message.reply_text("⚠️ በትክክል ያስገቡ።")

# --- 7. Main ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    start_cmds = ["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(start_cmds, start_handler))
    app_bot.add_handler(CommandHandler("rank2", rank2_cmd))
    
    admin_cmds = ["keep2", "info2", "log", "approve", "block", "unblock", "clear_rank2", "appt", "apptt"]
    app_bot.add_handler(CommandHandler(admin_cmds, admin_actions))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    print("Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
