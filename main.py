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

# --- 1. Flask Server (Render ላይ ቦቱ እንዳይዘጋ) ---
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
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0,
             mute_until TEXT, is_paused INTEGER DEFAULT 0, correct_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        if not os.path.exists('questions.json'): return []
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject: return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except: return []

async def get_user(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as c:
            return await c.fetchone()

# --- 5. Main Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u_data = await get_user(user.id)
    
    if update.effective_chat.type == "private":
        if user.id in ADMIN_IDS:
            await update.message.reply_text("✅ አድሚን ቦቱ ዝግጁ ነው።")
            return
        
        if u_data and u_data[4] == 1: # Rule 3: Blocked
            await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USER} ን ያነጋግሩ።")
            return

        if not u_data: # Rule 5: Registration
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
                await db.commit()
            await update.message.reply_text("👋 ምዝገባዎ ተልኳል። አድሚኑን በትዕግስት ይጠብቁ።")
            for admin in ADMIN_IDS:
                try: await context.bot.send_message(admin, f"🔔 አዲስ ተመዝጋቢ: {user.first_name} ({user.id})\nለማጽደቅ: `/approve {user.id}`")
                except: pass
            return

async def quiz_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    
    sub_map = {'history_srm2':'history', 'geography_srm2':'geography', 'mathematics_srm2':'mathematics', 'english_srm2':'english', 'start2':None}
    subject = sub_map.get(cmd)
    
    chat_id = update.effective_chat.id
    for j in context.job_queue.get_jobs_by_name(str(chat_id)): j.schedule_removal()
    
    async def send_q(ctx):
        if global_pause: return
        qs = load_questions(subject)
        if not qs: return
        q = random.choice(qs)
        try:
            m = await ctx.bot.send_poll(chat_id, f"[{q.get('subject','ALL')}] {q['q']}", q['o'], is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']))
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (m.poll.id, int(q['c']), chat_id))
                await db.commit()
        except: pass

    context.job_queue.run_repeating(send_q, 240, 5, name=str(chat_id))
    await update.message.reply_text(f"🚀 የ{subject if subject else 'ጠቅላላ'} ውድድር ተጀመረ!")

async def group_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private" and user.id not in ADMIN_IDS:
        # Rule 30: Illegal command punishment
        async with aiosqlite.connect('quiz_bot.db') as db:
            mute_time = (datetime.now() + timedelta(minutes=17)).isoformat()
            await db.execute("UPDATE users SET points = points - 3.17, mute_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ የህግ ጥሰት! {user.first_name} 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")

async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (tid,))
            await db.commit()
        await context.bot.send_message(tid, "🎉 ምዝገባዎ ጸድቋል! አሁን መሳተፍ ይችላሉ።")
        await update.message.reply_text(f"✅ {tid} ጸድቋል።")
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    u_id = ans.user.id
    u_data = await get_user(u_id)
    if not u_data or u_data[4] == 1 or global_pause: return
    
    # Check mute status
    if u_data[5] and datetime.fromisoformat(u_data[5]) > datetime.now(): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll = await c.fetchone()
    if not poll: return

    is_correct = ans.option_ids[0] == poll[0]
    points = 8 if (is_correct and poll[1] == 0) else (4 if is_correct else -1.5)

    async with aiosqlite.connect('quiz_bot.db') as db:
        col = "correct_count" if is_correct else "wrong_count"
        await db.execute(f"UPDATE users SET points = points + ?, {col} = {col} + 1 WHERE user_id = ?", (points, u_id))
        if is_correct and poll[1] == 0:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
        await db.commit()

# --- 8. Main execution ---
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    app_bot = Application.builder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler(["start", "rank2", "info2"], start_handler))
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], quiz_control))
    app_bot.add_handler(CommandHandler("approve", approve_cmd))
    app_bot.add_handler(CommandHandler("stop2", lambda u,c: [j.schedule_removal() for j in c.job_queue.get_jobs_by_name(str(u.effective_chat.id))] or u.message.reply_text("🛑 ውድድሩ ቆሟል።")))
    
    # Protection rules
    app_bot.add_handler(MessageHandler(filters.COMMAND & ~filters.ChatType.PRIVATE, group_guard))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    print("Bot is starting...")
    # drop_pending_updates=True በፎቶው ላይ ያየኸውን Conflict ይፈታዋል
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
