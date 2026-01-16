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

# --- 5. Quiz Logic ---
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
    points = 8 if (is_correct and poll_data[1] == 0) else (4 if is_correct else -1.5)

    async with aiosqlite.connect('quiz_bot.db') as db:
        col = "correct_count" if is_correct else "wrong_count"
        await db.execute(f"UPDATE users SET points = points + ?, {col} = {col} + 1 WHERE user_id = ?", (points, u_id))
        if is_correct and poll_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
        await db.commit()

# --- 6. Commands & Protection ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    u_data = await get_user_data(user.id)

    # Rule 2, 3, 5, 29: Private Chat Protection
    if chat_type == "private":
        if user.id in ADMIN_IDS:
            await update.message.reply_text("✅ አድሚን ቦቱ ዝግጁ ነው።")
            return
        
        if not u_data:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
                await db.commit()
            await update.message.reply_text(f"👋 ሰላም {user.first_name}!\nምዝገባው ላይ ነኝ፤ አድሚኑ ቢዚ ስለሆነ በትዕግስት ይጠብቁ።")
            for admin in ADMIN_IDS:
                await context.bot.send_message(admin, f"🔔 አዲስ ተመዝጋቢ: {user.first_name} ({user.id})\nማጽደቅ: `/approve {user.id}`")
            return
        
        # Rule 29: Illegal command in private
        valid_cmds = ['/start', '/rank2', '/info2']
        if update.message.text.split()[0] not in valid_cmds:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"⚠️ የህግ ጥሰት! ያለ ፈቃድ ትዕዛዝ በመጠቀሞ ታግደዋል። {ADMIN_USER} ን ያነጋግሩ።")
            return

    # Rule 4 & 30: Group Protection
    if chat_type != "private" and user.id not in ADMIN_IDS:
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} ያለ አድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።", reply_to_message_id=update.message.message_id)
        return

    # Rule 10-14, 27: Quiz Start
    cmd = update.message.text.split('@')[0][1:].lower()
    subs = {'history_srm2':'history', 'geography_srm2':'geography', 'mathematics_srm2':'mathematics', 'english_srm2':'english', 'start2':None}
    if cmd in subs or cmd == "start2":
        subject = subs.get(cmd)
        jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
        for j in jobs: j.schedule_removal()
        context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=update.effective_chat.id, data={'subject': subject}, name=str(update.effective_chat.id))
        await update.message.reply_text(f"🚀 የ{subject if subject else 'ጠቅላላ'} ውድድር ተጀመረ! (በየ 4 ደቂቃ)")
        for admin in ADMIN_IDS: await context.bot.send_message(admin, f"📢 ቦቱ በ {update.effective_chat.title} በ {user.first_name} አማካኝነት ተነስቷል።")

# --- Admin Specific Commands ---
async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    
    try:
        if cmd == "approve": # Rule 24
            tid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (tid,))
                await db.commit()
            await context.bot.send_message(tid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
            await update.message.reply_text(f"✅ {tid} ጸድቋል።")
        
        elif cmd == "anapprove": # Rule 6
            tid = int(context.args[0])
            await context.bot.send_message(tid, "❌ ጥያቄዎ ተቀባይነት አላገኘም። እባክዎ እንደገና ይሞክሩ።")
            await update.message.reply_text(f"⚠️ {tid} ውድቅ ተደርጓል።")

        elif cmd == "block": # Rule 19
            tid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (tid,))
                await db.commit()
            await context.bot.send_message(tid, f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USER} ን ያነጋግሩ።")
            await update.message.reply_text(f"🚫 {tid} ታግዷል።")

        elif cmd == "unmute": # Rule 30
            tid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (tid,))
                await db.commit()
            await update.message.reply_text(f"✅ ለተጠቃሚ {tid} እገዳው ተነስቷል።")

        elif cmd == "appt": # Rule 21
            global global_pause
            global_pause = True
            await update.message.reply_text(f"⏸ ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ቆሟል። {ADMIN_USER}")

        elif cmd == "apptt": # Rule 22
            global_pause = False
            await update.message.reply_text("▶️ ቦቱ በድጋሚ ስራ ጀምሯል።")

        elif cmd == "log": # Rule 24
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT username, correct_count, wrong_count, points FROM users") as c:
                    rows = await c.fetchall()
            res = "📜 የውድድር መዝገብ (Log):\n" + "\n".join([f"👤 {r[0]} | ✅ {r[1]} | ❌ {r[2]} | 💰 {r[3]}" for r in rows])
            await update.message.reply_text(res)

    except: await update.message.reply_text("❌ እባክዎ ID በትክክል ያስገቡ።")

async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for j in jobs: j.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        limit = 15 if update.effective_chat.type != "private" else 1
        async with db.execute(f"SELECT username, points FROM users ORDER BY points DESC LIMIT {limit}") as c:
            rows = await c.fetchall()
    res = "🏁 ውድድሩ ቆሟል!\n\n🏆 ውጤት:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
    await update.message.reply_text(res)
    for admin in ADMIN_IDS: await context.bot.send_message(admin, f"🛑 ቦቱ በ {update.effective_chat.title} በ {update.effective_user.first_name} አማካኝነት ቆሟል።")

# --- 7. Main Function ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # Registering handlers based on rules
    app_bot.add_handler(CommandHandler(["start", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "start2", "info2", "rank2", "keep"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "unblock", "unmute", "appt", "apptt", "log", "close", "clear_rank2"], admin_actions))
    app_bot.add_handler(CommandHandler("stop2", stop2_cmd))
    app_bot.add_handler(MessageHandler(filters.COMMAND & ~filters.ChatType.PRIVATE, start_handler)) # Protection
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
