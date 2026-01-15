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
BOT_STATUS = {"is_open": True, "open_time": None, "opener_name": "ያልታወቀ"}

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        # ነጥብ 10፡ ለታሪክ (hog) እንዲረዳ wrong_answers እና correct_answers ተጨምረዋል
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0,
             is_active INTEGER DEFAULT 1, wrong_answers INTEGER DEFAULT 0, correct_answers INTEGER DEFAULT 0)''')
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
    except Exception as e: return []

async def get_user_data(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT points, muted_until, is_blocked, status, is_active FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Quiz Logic ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    # ነጥብ 4 እና 5፡ ቦቱ በ /oppt የቆመ ከሆነ ጥያቄ አይልክም
    if not BOT_STATUS["is_open"]: return
    
    job = context.job
    chat_id = job.chat_id
    subject = job.data.get('subject')
    questions = load_questions(subject)
    
    if not questions: return

    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            chat_id, f"[{q.get('subject', 'ጠቅላላ')}] {q['q']}", q['o'], 
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
    
    # ነጥብ 3፡ ተጠቃሚው /close ከተደረገ መልስ አይቀበልም
    if not user or user[2] == 1 or user[3] != 'approved' or user[4] == 0: return 

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done, chat_id = poll_data
    
    # ነጥብ 2 እና 8፡ ውጤት አሰጣጥ
    is_correct = ans.option_ids[0] == correct_idx
    points = 8 if (is_correct and first_done == 0) else (4 if is_correct else 1.5)

    async with aiosqlite.connect('quiz_bot.db') as db:
        if is_correct:
            if first_done == 0: # ነጥብ 8፡ ማን ቀድሞ እንደመለሰ ማሳወቅ
                await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
                await context.bot.send_message(chat_id, f"🥇 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
            await db.execute("UPDATE users SET points = points + ?, correct_answers = correct_answers + 1 WHERE user_id = ?", (points, user_id))
            # ነጥብ 2፡ ሲያገኙ ማሳወቅ
            await context.bot.send_message(user_id, f"✅ ትክክል! {points} ነጥብ አግኝተዋል።")
        else:
            await db.execute("UPDATE users SET points = points + 1.5, wrong_answers = wrong_answers + 1 WHERE user_id = ?", (user_id,))
            # ነጥብ 2፡ ሲሳሳቱ ማሳወቅ
            await context.bot.send_message(user_id, "❌ ተሳስተሃል! ለተሳትፎ 1.5 ነጥብ ተሰጥቶሃል።")
        await db.commit()

# --- 6. New Commands (ነጥብ 3-11) ---

async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (tid,))
            await db.commit()
        await context.bot.send_message(tid, "⚠️ ጥያቄ መላኩ ለጊዜው ተቋርጦብሃል።")
        await update.message.reply_text(f"✅ ተጠቃሚ {tid} ታግዷል።")
    except: await update.message.reply_text("ID ያስገቡ።")

async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_active = 1 WHERE user_id = ?", (tid,))
            await db.commit()
        await context.bot.send_message(tid, "🚀 ጥያቄ መላኩ ተመልሶልሃል፤ መስራት ትችላለህ።")
        await update.message.reply_text(f"✅ ተጠቃሚ {tid} ተከፍቷል።")
    except: await update.message.reply_text("ID ያስገቡ።")

async def oppt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    BOT_STATUS["is_open"] = False
    await update.message.reply_text("⛔️ በAdmin ትዕዛዝ ውድድሩ ለጊዜው ቆሟል።")

async def opptt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    BOT_STATUS["is_open"] = True
    BOT_STATUS["open_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    BOT_STATUS["opener_name"] = update.effective_user.first_name
    await update.message.reply_text("✅ ውድድሩ ተመልሷል፤ መስራት ትችላላችሁ።")

async def kop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    # ነጥብ 6፡ ማን ከፈተው፣ መቼ፣ ማን እየተሳተፈ ነው
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username FROM users WHERE status='approved' AND is_active=1") as cursor:
            active_users = await cursor.fetchall()
    
    users_list = ", ".join([u[0] for u in active_users]) if active_users else "ማንም የለም"
    msg = f"🔍 የቦቱ ሁኔታ፦\n🔓 የከፈተው፦ {BOT_STATUS['opener_name']}\n⏰ ሰዓት፦ {BOT_STATUS['open_time']}\n👥 ተሳታፊዎች፦ {users_list}"
    await update.message.reply_text(msg)

async def start2_special(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ነጥብ 7፡ /kop[id] ሲደረግ የሚመጣውን /start2 ትዕዛዝ ማስተናገጃ
    await update.message.reply_text("🔄 ውድድሩን መልሰህ እየጀመርክ ነው...")
    await start_handler(update, context)

async def hog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ነጥብ 10፡ ሙሉ ታሪክ
    user_id = update.effective_user.id
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_answers, wrong_answers, points FROM users WHERE user_id=?", (user_id,)) as c:
            r = await c.fetchone()
    if r:
        await update.message.reply_text(f"📜 ያንተ ታሪክ፦\n✅ ትክክል፦ {r[0]}\n❌ ስህተት፦ {r[1]}\n💰 ጠቅላላ ነጥብ፦ {r[2]}")

async def security_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ነጥብ 11፡ ያልተፈቀደ ትዕዛዝ ብሎክ ማድረጊያ
    user = update.effective_user
    if user.id in ADMIN_IDS: return
    
    msg_text = update.message.text
    allowed_cmds = ['/start', '/start2', '/hog', '/rank2']
    
    if msg_text.startswith('/') and msg_text.split()[0] not in allowed_cmds:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"🚫 ያልተፈቀደ ትዕዛዝ አዘሃል! በዚ ምክንያት ታግደሃል። @penguiner ን ጠይቅ።")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"🚨 ተጠቃሚ {user.first_name} ({user.id}) ያልተፈቀደ ትዕዛዝ በመጠቀሙ ታግዷል።")

# --- 7. Original Commands (ከተሰጠኝ ኮድ ያልተቀነሱ) ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user_data = await get_user_data(user.id)

    if chat_type == "private":
        if not user_data:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
                await db.commit()
            await update.message.reply_text(f"👋 ሰላም {user.first_name}!\nየምዝገባ ጥያቄዎ በሂደት ላይ ነው።")
            # ነጥብ 9፡ ቦቱ በግል ሲጠየቅ የሚመልሰው
            await update.message.reply_text(f"🔔 {user.first_name} መወዳደር ጀምረሃል!")
            for admin in ADMIN_IDS:
                try: await context.bot.send_message(admin, f"👤 አዲስ ምዝገባ\nID: {user.id}\n/approve {user.id}")
                except: pass
            return
        elif user_data[2] == 1:
            await update.message.reply_text("🚫 @penguiner ን ያነጋግሩ።")
            return

    if user.id not in ADMIN_IDS:
        if chat_type != "private":
            mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
                await db.commit()
            await update.message.reply_text(f"⚠️ {user.first_name} 3.17 ነጥብ ተቀንሶብዎታል!")
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subject = cmd.split('_')[0] if "_" in cmd else None
    
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    # ነጥብ 1፡ አክቲቭ ሲያደርጉ ለኔ ማሳወቅ
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"✅ ውድድር በ {update.effective_chat.title} ተጀምሯል።")
    await update.message.reply_text(f"🚀 የ{subject if subject else 'ሁሉም'} ውድድር ተጀምሯል!")

# (ሌሎች የድሮ ተግባራት: approve_cmd, rank2_cmd, stop2_cmd, hoo2_cmd, block_cmd, unblock_cmd, clear_rank2 እዚህ ይቀጥላሉ...)
async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        tid = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (tid,))
            await db.commit()
        await update.message.reply_text(f"✅ ተጠቃሚ {tid} ጸድቋል።")
    except: pass

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "📊 ደረጃ፦\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)]) if rows else "ነጥብ የለም"
    await update.message.reply_text(res)

async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for j in jobs: j.schedule_removal()
    await update.message.reply_text("🏁 ውድድሩ ተቋርጧል።")

# --- 8. Main Function ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    start_cmds = ["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(start_cmds, start_handler))
    app_bot.add_handler(CommandHandler("rank2", rank2_cmd))
    app_bot.add_handler(CommandHandler("approve", approve_cmd))
    app_bot.add_handler(CommandHandler("stop2", stop2_cmd))
    app_bot.add_handler(CommandHandler("close", close_cmd))
    app_bot.add_handler(CommandHandler("open", open_cmd))
    app_bot.add_handler(CommandHandler("oppt", oppt_cmd))
    app_bot.add_handler(CommandHandler("opptt", opptt_cmd))
    app_bot.add_handler(CommandHandler("kop", kop_cmd))
    app_bot.add_handler(CommandHandler("hog", hog_cmd))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(MessageHandler(filters.COMMAND, security_block)) # ነጥብ 11
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
