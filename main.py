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

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIG ---
TOKEN = "8256328585:AAHTvHxxChdIohofHdDcrOeTN1iEbWcx9QI"
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- HELPERS ---
def load_questions(subject=None):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject:
                return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except: return []

async def is_user_registered(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT status, is_blocked FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row if row else None

# --- QUIZ ENGINE ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    questions = load_questions(job.data.get('subject'))
    if not questions: return
    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            job.chat_id, f"[{q.get('subject', 'ጠቅላላ')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], job.chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user_info = await is_user_registered(user_id)
    
    if not user_info or user_info[1] == 1: return # ያልተመዘገበ ወይም የታገደ አይሳተፍም

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] and datetime.now(timezone.utc) < datetime.fromisoformat(row[0]): return

        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done, chat_id = poll_data
    points = 8 if (ans.option_ids[0] == correct_idx and first_done == 0) else (4 if ans.option_ids[0] == correct_idx else 1.5)

    if points == 8:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
            await db.commit()
        await context.bot.send_message(chat_id, f"🏆 እንኳን ደስ አለዎት {ans.user.first_name}! ቀድመው በመመለስዎ 8 ነጥብ አግኝተዋል።")

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMANDS ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    user_info = await is_user_registered(user.id)

    # በግል ሲሆን ምዝገባ ይጠይቃል
    if chat_type == "private":
        if not user_info:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'approved')", (user.id, user.first_name))
                await db.commit()
            await update.message.reply_text(f"👋 ሰላም {user.first_name}! በተሳካ ሁኔታ ተመዝግበዋል። አሁን ውድድሩን መጀመር ይችላሉ።")
            return
        elif user_info[1] == 1:
            await update.message.reply_text("🚫 ውድ ተጠቃሚ... ባልታወቀ ምክንያት ለጊዜው መጠቀም አይችሉም። እባክዎ @penguiner ን ያነጋግሩ።")
            return

    # ትዕዛዝ አስተዳደር
    if user.id not in ADMIN_IDS:
        if chat_type != "private": # ግሩፕ ላይ ከሆነ ይቀጣል
            mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
                await db.commit()
            await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶብዎታል፤ ለ 17 ደቂቃም ታግደዋል።")
        return

    # ትዕዛዞችን ማስፈጸም (start2, history_srm2 etc.)
    cmd = update.message.text.split('@')[0][1:].lower()
    subject = cmd.split('_')[0] if "_" in cmd else None
    if subject == "start2": subject = None

    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, 240, 5, update.effective_chat.id, data={'subject': subject}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🔔 ውድድሩ ተጀምሯል! መልካም ዕድል!")

async def hoo2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            count = await cursor.fetchone()
    await update.message.reply_text(f"👥 እስካሁን የተመዘገቡ ተወዳዳሪዎች ብዛት፡ {count[0]}")

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target_id,))
            await db.commit()
        await update.message.reply_text(f"🚫 ተጠቃሚ {target_id} ታግደዋል።")
    except: await update.message.reply_text("ትክክለኛ ID ያስገቡ። ለምሳሌ፡ `/block 123456`")

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "📊 ወቅታዊ የደረጃ ሰንጠረዥ፦\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)]) if rows else "📊 እስካሁን ነጥብ የለም።"
    await update.message.reply_text(res)

async def clear_rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ነጥቦች ተሰርዘዋል። (ምዝገባው አልተነካም)")

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    cmds = ["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(cmds, start_handler))
    app_bot.add_handler(CommandHandler("rank2", rank2_cmd))
    app_bot.add_handler(CommandHandler("clear_rank2", clear_rank2))
    app_bot.add_handler(CommandHandler("hoo2", hoo2_cmd))
    app_bot.add_handler(CommandHandler("block", block_cmd))
    app_bot.add_handler(CommandHandler("stop2", lambda u, c: [j.schedule_removal() for j in c.job_queue.get_jobs_by_name(str(u.effective_chat.id))] or u.message.reply_text("🏁 ተጠናቋል።")))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
