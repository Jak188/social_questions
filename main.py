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

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIG ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- HELPERS ---
def load_questions(subject=None):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject:
                # ትምህርቱን ለይቶ ማውጣት
                return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except: return []

# --- QUIZ ENGINE ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    subject = job_data.get('subject')
    chat_id = context.job.chat_id
    
    questions = load_questions(subject)
    if not questions: return
    
    q = random.choice(questions)
    sub_label = q.get('subject', 'ጠቅላላ')
    try:
        msg = await context.bot.send_poll(
            chat_id, f"[{sub_label}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], chat_id))
            await db.commit()
    except Exception as e:
        print(f"Error sending poll: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                if datetime.now(timezone.utc) < datetime.fromisoformat(row[0]): return

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
            await context.bot.send_message(chat_id, f"🏆 እንኳን ደስ አለዎት {ans.user.first_name}! ቀድመው በትክክል በመመለስዎ 8 ነጥብ አግኝተዋል።")
        else: points = 4
    else: points = 1.5

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, ans.user.first_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMANDS ---
async def start_quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id not in ADMIN_IDS:
        until = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user_id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {update.effective_user.first_name} የአድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶብዎታል፤ ለ 17 ደቂቃም ታግደዋል።")
        return

    # ትዕዛዙን መለየት (ለምሳሌ /History_srm2 ከሆነ History ን መውሰድ)
    cmd = update.message.text.split('@')[0][1:].lower()
    subject = None
    if "_" in cmd:
        subject = cmd.split('_')[0]
    
    # የድሮ ስራ ካለ ማቆም
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs: job.schedule_removal()

    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    
    sub_text = f"የ {subject.capitalize()}" if subject else "የሁሉም ትምህርቶች"
    await update.message.reply_text(f"🔔 {sub_text} ውድድር በይፋ ተጀምሯል! የመጀመሪያው ጥያቄ አሁን ይቀርባል። መልካም ዕድል!")

async def rank2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        # ነጥባቸው ከ 0 በላይ የሆኑትን ብቻ ማሳየት
        async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        await update.message.reply_text("📊 እስካሁን ነጥብ ያስመዘገበ ተወዳዳሪ የለም።")
        return
        
    res = "📊 ወቅታዊ የደረጃ ሰንጠረዥ፦\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for job in jobs: job.schedule_removal()
    await update.message.reply_text("🏁 ውድድሩ ተጠናቋል።")
    await rank2_cmd(update, context)

async def clear_rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ሁሉም ነጥቦች ተሰርዘዋል። አዲስ ውድድር መጀመር ይቻላል።")

async def un_mute2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS or not update.message.reply_to_message: return
    target = update.message.reply_to_message.from_user
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target.id,))
        await db.commit()
    await update.message.reply_text(f"✅ {target.first_name} ተለቀዋል፤ ማስጠንቀቂያ ተሰጥቷቸዋል።")

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm"], start_quiz_cmd))
    app_bot.add_handler(CommandHandler("stop2", stop2_cmd))
    app_bot.add_handler(CommandHandler("rank2", rank2_cmd))
    app_bot.add_handler(CommandHandler("clear_rank2", clear_rank2))
    app_bot.add_handler(CommandHandler("un_mute2", un_mute2_cmd))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
