import os
import json
import asyncio
import random
import aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

# --- 1. Flask Server (Keep-Alive) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'approved', muted_until TEXT, is_blocked INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject:
                return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except: return []

async def get_user(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT points, muted_until, is_blocked FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Quiz Logic ---
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
    except Exception as e: print(f"Poll Error: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user_data = await get_user(user_id)
    
    if not user_data or user_data[2] == 1: return # ያልተመዘገበ ወይም የታገደ አይሳተፍም

    # የ Mute ቼክ
    if user_data[1] and datetime.now(timezone.utc) < datetime.fromisoformat(user_data[1]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done, chat_id = poll_data
    
    points = 0
    if ans.option_ids[0] == correct_idx:
        if first_done == 0:
            points = 8
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
                await db.commit()
            await context.bot.send_message(chat_id, f"🏆 እንኳን ደስ አለዎት {ans.user.first_name}! ቀድመው በመመለስዎ 8 ነጥብ አግኝተዋል።")
        else: points = 4
    else: points = 1.5

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- 6. Command Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user_data = await get_user(user.id)

    # ምዝገባ በግል (Private)
    if chat_type == "private" and not user_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"👋 ሰላም {user.first_name}! በተሳካ ሁኔታ ተመዝግበዋል። አሁን ውድድሩን መሳተፍ ይችላሉ።")
        if user.id in ADMIN_IDS: pass
        else: return

    # የታገደ ሰው ቼክ
    if user_data and user_data[2] == 1:
        await update.message.reply_text("🚫 ውድ ተጠቃሚ... ባልታወቀ ምክንያት ለጊዜው መጠቀም አይችሉም። እባክዎ @penguiner ን ያነጋግሩ።")
        return

    # አድሚን ካልሆነና ትዕዛዝ ከነካ ቅጣት (በግሩፕ)
    if user.id not in ADMIN_IDS:
        if chat_type != "private":
            mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
                await db.commit()
            await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶብዎታል፤ ለ 17 ደቂቃም ታግደዋል።")
        return

    # ውድድር ማስጀመር
    cmd = update.message.text.split('@')[0][1:].lower()
    subject = cmd.split('_')[0] if "_" in cmd else None
    if subject == "start2": subject = None

    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    
    context.job_queue.run_repeating(send_quiz, 240, 5, chat_id, data={'subject': subject}, name=str(chat_id))
    sub_txt = f"የ {subject.capitalize()}" if subject else "የሁሉም ትምህርቶች"
    await update.message.reply_text(f"🔔 {sub_txt} ውድድር በይፋ ተጀምሯል! መልካም ዕድል!")

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "📊 ወቅታዊ የደረጃ ሰንጠረዥ፦\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)]) if rows else "📊 እስካሁን ነጥብ ያስመዘገበ የለም።"
    await update.message.reply_text(res)

async def hoo2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: total = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1") as c2: blocked = await c2.fetchone()
    await update.message.reply_text(f"👥 **የተጠቃሚዎች መረጃ**\n\n🔹 ጠቅላላ ተመዝጋቢ፡ {total[0]}\n🚫 የታገዱ ተጠቃሚዎች፡ {blocked[0]}")

async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (tid,))
            await db.commit()
        try: await context.bot.send_message(tid, "🚫 ውድ ተጠቃሚ... ባልታወቀ ምክንያት ለጊዜው መጠቀም አይችሉም። እባክዎ @penguiner ን ያነጋግሩ።")
        except: pass
        await update.message.reply_text(f"🚫 ተጠቃሚ {tid} ታግደዋል።")
    except: await update.message.reply_text("ID በትክክል ያስገቡ።")

async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (tid,))
            await db.commit()
        try: await context.bot.send_message(tid, "🎉 እንኳን ደስ አለዎት! የእገዳ ጊዜዎ ተጠናቋል። አሁን መጠቀም ይችላሉ።")
        except: pass
        await update.message.reply_text(f"✅ ተጠቃሚ {tid} ተለቀዋል።")
    except: await update.message.reply_text("ID በትክክል ያስገቡ።")

async def clear_rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ነጥቦች ተሰርዘዋል።")

# --- 7. Main Function ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    start_cmds = ["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(start_cmds, start_handler))
    app_bot.add_handler(CommandHandler("rank2", rank2_cmd))
    app_bot.add_handler(CommandHandler("hoo2", hoo2_cmd))
    app_bot.add_handler(CommandHandler("block", block_cmd))
    app_bot.add_handler(CommandHandler("unblock", unblock_cmd))
    app_bot.add_handler(CommandHandler("clear_rank2", clear_rank2))
    app_bot.add_handler(CommandHandler("stop2", lambda u, c: [j.schedule_removal() for j in c.job_queue.get_jobs_by_name(str(u.effective_chat.id))] or u.message.reply_text("🏁 ተጠናቋል።")))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
