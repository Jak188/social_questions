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

# --- 1. Flask Server (Keep Alive) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
global_pause = False

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0,
             last_active TEXT, correct_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0,
             is_paused INTEGER DEFAULT 0, mute_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject: return [q for q in all_q if q.get('subject','').lower() == subject.lower()]
            return all_q
    except: return []

async def get_user(u_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (u_id,)) as c: return await c.fetchone()

# --- 5. Quiz Sending Logic ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if global_pause: return
    job = context.job
    qs = load_questions(job.data.get('sub'))
    if not qs: return
    q = random.choice(qs)
    try:
        msg = await context.bot.send_poll(job.chat_id, f"[{q.get('subject','ALL')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']))
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, int(q['c']), job.chat_id))
            await db.commit()
    except: pass

# --- 6. Commands & Rules ---
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    # Rule 9: Admin Notification
    if user.id in ADMIN_IDS:
        await update.message.reply_text("✅ ቦቱ ስራ ጀምሯል።")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"🚀 አድሚን {user.first_name} ቦቱን አስነስቷል።")
        return

    # Rule 3 & 29: Private User Rule
    if chat.type == "private":
        if u_data and u_data[4] == 1: # Blocked
            await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ።")
            return
        
        if not u_data:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status) VALUES (?,?,?)", (user.id, user.first_name, 'pending'))
                await db.commit()
            await update.message.reply_text("👋 ምዝገባዎ ተልኳል። አድሚኑ ቢዚ ስለሆነ በትዕግስት ይጠብቁ።")
            for admin in ADMIN_IDS:
                await context.bot.send_message(admin, f"🔔 አዲስ ተመዝጋቢ: {user.first_name} ({user.id})\n/approve {user.id}")
            return
        
        if u_data[3] == 'pending':
            await update.message.reply_text("⏳ አድሚኑ ገና አላጸደቀዎትም፣ እባክዎ በትዕግስት ይጠብቁ።")
            return

    # Rule 4 & 30: Group Illegal Command Punishment
    if chat.type != "private" and user.id not in ADMIN_IDS:
        async with aiosqlite.connect('quiz_bot.db') as db:
            mute_time = (datetime.now() + timedelta(minutes=17)).isoformat()
            await db.execute("UPDATE users SET points = points - 3.17, mute_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_to_message.reply_text(f"⚠️ የህግ ጥሰት! {user.first_name} 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግዷል።")
        return

async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (tid,))
            await db.commit()
        await context.bot.send_message(tid, "🎉 ምዝገባዎ ተቀብሏል! አሁን መሳተፍ ይችላሉ።")
        await update.message.reply_text(f"✅ {tid} ጸድቋል።")
    except: pass

async def unapprove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        await context.bot.send_message(tid, "❌ ይቅርታ፣ ጥያቄዎ ተቀባይነት አላገኘም። እባክዎ እንደገና ይሞክሩ።")
        await update.message.reply_text(f"⚠️ {tid} ተሰርዟል።")
    except: pass

async def start_quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].replace('start2', 'all')
    sub = cmd.split('_')[0] if cmd != 'all' else None
    
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for j in jobs: j.schedule_removal()
    
    context.job_queue.run_repeating(send_quiz, 240, 5, update.effective_chat.id, data={'sub': sub}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🚀 የ {sub if sub else 'ጠቅላላ'} ውድድር ተጀምሯል! (በየ 4 ደቂቃ)")

async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as c:
            rows = await c.fetchall()
    
    res = "🏁 ውድድሩ ቆሟል!\n\n🏆 የደረጃ ሰንጠረዥ (Top 15):\n"
    res += "\n".join([f"{i+1}. {r[0]} - {r[1]} pt" for i, r in enumerate(rows)])
    await update.message.reply_text(res)
    for admin in ADMIN_IDS: await context.bot.send_message(admin, f"🛑 ቦቱ በ {update.effective_chat.title} ቆሟል።")

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (tid,))
            await db.commit()
        await update.message.reply_text(f"🚫 {tid} ታግዷል። (አልታወቀም ይላል)")
    except: pass

async def appt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    global global_pause
    global_pause = True
    await update.message.reply_text(f"⏸ ከአድሚን በመጣ ትዕዛዝ ቦቱ ለጊዜው ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ።")

async def apptt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    global global_pause
    global_pause = False
    await update.message.reply_text("▶️ ቦቱ ተከፍቷል፣ ውድድሩ ቀጥሏል!")

async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_paused = 1 WHERE user_id = ?", (tid,))
            await db.commit()
        await context.bot.send_message(tid, "⏸ ቦቱ ለጊዜው ስለማይፈለግ ታግዶባችኋል።")
    except: pass

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET mute_until = NULL WHERE user_id = ?", (tid,))
            await db.commit()
        await update.message.reply_text(f"✅ የ {tid} እገዳ ተነስቷል።")
    except: pass

# --- 7. Answer Handling (Rule 28) ---
async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    u_id = ans.user.id
    u_data = await get_user(u_id)
    
    if not u_data or u_data[4] == 1 or u_data[8] == 1 or global_pause: return
    if u_data[9] and datetime.fromisoformat(u_data[9]) > datetime.now(): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll = await c.fetchone()
    if not poll: return

    is_correct = ans.option_ids[0] == poll[0]
    points = 8 if (is_correct and poll[1] == 0) else (4 if is_correct else -1.5)

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ?, last_active = ? WHERE user_id = ?", (points, datetime.now().isoformat(), u_id))
        if is_correct and poll[1] == 0:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
        await db.commit()

# --- 8. Main Function ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # Registering all commands
    start_cmds = ["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(start_cmds, handle_start))
    app_bot.add_handler(CommandHandler(["history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "start2"], start_quiz_cmd))
    app_bot.add_handler(CommandHandler("approve", approve_cmd))
    app_bot.add_handler(CommandHandler("unapprove", unapprove_cmd))
    app_bot.add_handler(CommandHandler("stop2", stop2_cmd))
    app_bot.add_handler(CommandHandler("block", block_cmd))
    app_bot.add_handler(CommandHandler("appt", appt_cmd))
    app_bot.add_handler(CommandHandler("apptt", apptt_cmd))
    app_bot.add_handler(CommandHandler("close", close_cmd))
    app_bot.add_handler(CommandHandler("unmute", unmute_cmd))
    app_bot.add_handler(CommandHandler("rank2", lambda u,c: u.message.reply_text("📊 /rank2... (ደረጃ ሰንጠረዥ)"))) # Add full logic as needed
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
