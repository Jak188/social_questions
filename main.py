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

# --- Uptime Server ለ Render ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN", "8256328585:AAHTvHxxChdIohofHdDcrOeTN1iEbWcx9QI")
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE SETUP ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        # Rule 13: ነጥብ እና መረጃ በዳታቤዝ
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- HELPERS ---
def load_questions(subject):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            return [q for q in all_q if q.get('subject') == subject]
    except: return []

async def check_user_status(user_id, chat_type):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT status, muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            # Rule 12: በግል (private) ለማውራት ምዝገባ ያስፈልጋል
            if chat_type == "private" and (not row or row[0] != 'approved'):
                return "unauthorized", None
            # Rule 14: የታገደ ሰው
            if row and row[1] and datetime.now() < datetime.fromisoformat(row[1]):
                return "muted", row[1]
            return "ok", None

# --- QUIZ LOGIC ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    subject = context.job.data['subject']
    questions = load_questions(subject)
    if not questions: return
    q = random.choice(questions)
    # Rule 15 & 22: በየ 4 ደቂቃው ጥያቄ ከማብራሪያ (exp) ጋር
    msg = await context.bot.send_poll(
        context.job.chat_id, q['q'], q['o'], is_anonymous=False, 
        type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
    )
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], context.job.chat_id))
        await db.commit()

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    # Rule 11 & 12: ግሩፕ ላይ ምዝገባ አይጠይቅም፣ በግል ግን ይጠይቃል
    status, _ = await check_user_status(user_id, "group") # answer is always processed if not muted
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] and datetime.now() < datetime.fromisoformat(row[0]): return

        async with db.execute("SELECT correct_option, first_done FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done = poll_data
    points = 0
    if ans.option_ids[0] == correct_idx:
        if first_done == 0:
            points = 8 # Rule 16: ቀድሞ የመለሰ 8 ነጥብ
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
                await db.commit()
        else: points = 4 # Rule 17: ዘግይቶ የመለሰ 4 ነጥብ
    else: points = 1.5 # Rule 18: ለተሳሳተ 1.5 ነጥብ

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, ans.user.first_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMANDS ---
async def start2_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 1 & 12: የግል ምዝገባ ማስጀመሪያ
    user = update.effective_user
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.first_name))
        await db.commit()
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"👤 አዲስ የምዝገባ ጥያቄ:\nስም: {user.first_name}\nID: `{user.id}`\nለማጽደቅ: `/approve {user.id}`")
    await update.message.reply_text("ጥያቄህ ለአድሚን ተልኳል፤ ሲፈቀድልህ ቦቱን በግል መጠቀም ትችላለህ።")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = context.args[0]
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
        await update.message.reply_text(f"✅ ተጠቃሚ {target_id} ጸድቋል።")
    except: await update.message.reply_text("እባክህ ID ቁጥሩን ጨምር።")

async def start_subject_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 7-10: የትምህርት አይነት ውድድር ማስጀመሪያ
    if update.effective_user.id not in ADMIN_IDS: return
    subject = update.message.text.split('_')[0][1:].capitalize().replace('srm2', '').replace('srm', '')
    context.job_queue.run_repeating(send_quiz, 240, 1, update.effective_chat.id, {'subject': subject}, name=str(update.effective_chat.id))
    await update.message.reply_text(f"🚀 የ {subject} ውድድር በየ 4 ደቂቃው ተጀመረ!")

async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 2 & 20: ማቆም እና ደረጃ ማሳየት
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for job in jobs: job.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "🏁 ውድድሩ ቆሟል!\n🏆 የአሸናፊዎች ደረጃ:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def mute2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 6 & 21: በሪፕላይ ማገድ
    if update.effective_user.id not in ADMIN_IDS or not update.message.reply_to_message: return
    target = update.message.reply_to_message.from_user
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, target.id))
        await db.commit()
    await update.message.reply_text(f"🚫 {target.first_name} ለ 17 ደቂቃ ታግዷል (3.17 ነጥብ ተቀንሷል)።")

async def un_mute2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 4 & 19: እገዳ ማንሳት
    if update.effective_user.id not in ADMIN_IDS or not update.message.reply_to_message: return
    target = update.message.reply_to_message.from_user
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target.id,))
        await db.commit()
    await update.message.reply_text(f"✅ {target.first_name} ተለቅቋል፤ ማስጠንቀቂያ ተሰጥቶታል።")

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 3: ደረጃ ማሳየት
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "🏆 ወቅታዊ ደረጃ:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def handle_violation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 14: አድሚን ትእዛዝ ለመንካት የሞከረ ሰው ቅጣት
    user = update.effective_user
    if user.id in ADMIN_IDS: return
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user.id))
        await db.commit()
    await update.message.reply_text(f"⚠️ {user.first_name} በአድሚን ትእዛዝ ጣልቃ በመግባትህ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደሃል!")

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    application = Application.builder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start2", start2_registration))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler(["History_srm2", "Geography_srm2", "Mathematics_srm2", "English_srm"], start_subject_quiz))
    application.add_handler(CommandHandler("stop2", stop2_cmd))
    application.add_handler(CommandHandler("mute2", mute2_cmd))
    application.add_handler(CommandHandler("un_mute2", un_mute2_cmd))
    application.add_handler(CommandHandler("rank2", rank2_cmd))
    application.add_handler(CommandHandler("clear_rank2", lambda u, c: None)) # Add clear logic if needed
    
    # Rule 14: Non-admin protection
    application.add_handler(MessageHandler(filters.Regex(r'^\/.*2$') & ~filters.User(ADMIN_IDS), handle_violation))
    
    application.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
