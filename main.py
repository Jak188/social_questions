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
global_pause = False  # ለ /oppt እና /opptt

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0,
             last_active TEXT, correct_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0,
             is_paused INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
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
    except: return []

async def get_user_data(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Quiz Logic ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if global_pause: return
    job = context.job
    questions = load_questions(job.data.get('subject'))
    if not questions: return
    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            job.chat_id, f"[{q.get('subject', 'ጠቅላላ')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, int(q['c']), job.chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    u_id = ans.user.id
    user = await get_user_data(u_id)
    
    # ተጠቃሚው ብሎክ ከሆነ፣ የተዘጋ ከሆነ ወይም ፖዝ ከተደረገ አይሰራም
    if not user or user[5] == 1 or user[9] == 1 or global_pause: return 

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll = await cursor.fetchone()
    if not poll: return

    is_correct = ans.option_ids[0] == poll[0]
    points = 8 if (is_correct and poll[1] == 0) else (4 if is_correct else 1.5)

    # ዳታቤዝ ማዘመን (ታሪክን ጨምሮ)
    async with aiosqlite.connect('quiz_bot.db') as db:
        col = "correct_count" if is_correct else "wrong_count"
        await db.execute(f"UPDATE users SET points = points + ?, {col} = {col} + 1, last_active = ? WHERE user_id = ?", 
                         (points, datetime.now().isoformat(), u_id))
        if is_correct and poll[1] == 0:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
            await context.bot.send_message(poll[2], f"🥇 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አገኘ!")
        await db.commit()

    # አድሚን ሪፖርት (ህግ 2)
    report = f"👤 {ans.user.first_name} ({u_id}) " + ("በትክክል መለሰ ✅" if is_correct else "ተሳሳተ ❌")
    for admin in ADMIN_IDS:
        try: await context.bot.send_message(admin, report)
        except: pass

# --- 6. Commands ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u_data = await get_user_data(user.id)
    chat_type = update.effective_chat.type

    # የደህንነት ህግ (ህግ 11) - አድሚን ያልሆነ ሰው የግል ትዕዛዝ ሲልክ
    if chat_type == "private" and user.id not in ADMIN_IDS:
        if not u_data:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status, last_active) VALUES (?, ?, 'pending', ?)", 
                                 (user.id, user.first_name, datetime.now().isoformat()))
                await db.commit()
            await update.message.reply_text("👋 የምዝገባ ጥያቄዎ በሂደት ላይ ነው። እባክዎ ማረጋገጫ ይጠብቁ።")
            for admin in ADMIN_IDS:
                await context.bot.send_message(admin, f"🔔 አዲስ ተመዝጋቢ: {user.first_name} ({user.id})\nለማጽደቅ: `/approve {user.id}`")
            return
        else:
            # ያልተፈቀደ ትዕዛዝ ከላከ ብሎክ ይደረጋል (ህግ 11)
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text("🚫 ያልተፈቀደ ትዕዛዝ አዘዋል። ለምን እንደሆነ @penguiner ን ይጠይቁ።")
            for admin in ADMIN_IDS:
                await context.bot.send_message(admin, f"🚨 ተጠቃሚ {user.first_name} ({user.id}) ያልተፈቀደ ትዕዛዝ በመጠቀሙ ታግዷል።")
            return

    if user.id not in ADMIN_IDS: return

    # ውድድር ማስጀመር
    cmd = update.message.text.split('@')[0][1:].lower()
    subject = cmd.split('_')[0] if "_" in cmd else None
    if subject == "start2": subject = None

    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, 240, 5, update.effective_chat.id, data={'subject': subject}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🚀 የ{subject if subject else 'ጠቅላላ'} ውድድር ተጀምሯል!")

# ህግ 3: /close እና /open
async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    tid = int(context.args[0])
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET is_paused = 1 WHERE user_id = ?", (tid,))
        await db.commit()
    try: await context.bot.send_message(tid, "⏸ ውድድሩ ለእርስዎ ለጊዜው ቆሟል።")
    except: pass
    await update.message.reply_text(f"✅ ተጠቃሚ {tid} ለጊዜው ታግዷል።")

async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    tid = int(context.args[0])
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET is_paused = 0 WHERE user_id = ?", (tid,))
        await db.commit()
    try: await context.bot.send_message(tid, "▶️ ውድድሩ ለእርስዎ ተከፍቷል። አሁን መስራት ይችላሉ።")
    except: pass
    await update.message.reply_text(f"✅ ተጠቃሚ {tid} ተለቋል።")

# ህግ 4 & 5: /oppt እና /opptt
async def oppt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    global global_pause
    global_pause = True
    await update.message.reply_text("⏸ ውድድሩ በአድሚኑ ትዕዛዝ ለሁሉም ቆሟል።")

async def opptt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    global global_pause
    global_pause = False
    await update.message.reply_text("▶️ ውድድሩ ተቀጥሏል።")

# ህግ 6 & 7: /kop
async def kop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    if context.args:
        tid = int(context.args[0])
        try: await context.bot.send_message(tid, "⚠️ ውድድሩን እየተሳተፉ ስላልሆነ ቆሟል። ለመቀጠል /start2 ይበሉ።")
        except: pass
        await update.message.reply_text(f"🔔 ለ {tid} ማስጠንቀቂያ ተልኳል።")
        return
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, last_active FROM users WHERE status='approved'") as cursor:
            rows = await cursor.fetchall()
    res = "🔍 የተሳትፎ ክትትል:\n" + "\n".join([f"👤 {r[0]} | መጨረሻ የታየው: {r[1][:16]}" for r in rows])
    await update.message.reply_text(res)

# ህግ 10: /hog (ታሪክ)
async def hog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, correct_count, wrong_count, points FROM users") as cursor:
            rows = await cursor.fetchall()
    res = "📚 የተወዳዳሪዎች ታሪክ:\n\n"
    for r in rows:
        res += f"👤 {r[0]}\n✅ ያገኘው: {r[1]} | ❌ የሳተው: {r[2]} | 💰 ነጥብ: {r[3]}\n\n"
    await update.message.reply_text(res)

# ሌሎች ትዕዛዞች (rank2, approve, stop2, hoo2, block, unblock)
async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    tid = int(context.args[0])
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET status = 'approved', last_active = ? WHERE user_id = ?", (datetime.now().isoformat(), tid))
        await db.commit()
    try: await context.bot.send_message(tid, "🎉 እንኳን ደስ አለዎት! ተቀባይነት አግኝተዋል።")
    except: pass
    await update.message.reply_text(f"✅ {tid} ጸድቋል።")

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "📊 ደረጃ:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
    await update.message.reply_text(res if rows else "ነጥብ የለም።")

# --- 7. Main Function ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    start_cmds = ["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(start_cmds, start_handler))
    app_bot.add_handler(CommandHandler("approve", approve_cmd))
    app_bot.add_handler(CommandHandler("close", close_cmd))
    app_bot.add_handler(CommandHandler("open", open_cmd))
    app_bot.add_handler(CommandHandler("oppt", oppt_cmd))
    app_bot.add_handler(CommandHandler("opptt", opptt_cmd))
    app_bot.add_handler(CommandHandler("kop", kop_cmd))
    app_bot.add_handler(CommandHandler("hog", hog_cmd))
    app_bot.add_handler(CommandHandler("rank2", rank2_cmd))
    app_bot.add_handler(CommandHandler("block", lambda u,c: asyncio.create_task(block_cmd(u,c))))
    app_bot.add_handler(CommandHandler("unblock", lambda u,c: asyncio.create_task(unblock_cmd(u,c))))
    app_bot.add_handler(CommandHandler("stop2", lambda u,c: [j.schedule_removal() for j in c.job_queue.get_jobs_by_name(str(u.effective_chat.id))] or u.message.reply_text("🏁 ቆሟል።")))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
