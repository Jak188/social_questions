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
             status TEXT DEFAULT 'pending', muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.commit()

# --- HELPERS ---
def load_all_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return []

# --- QUIZ ENGINE ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    questions = load_all_questions()
    if not questions: return
    q = random.choice(questions)
    
    # Rule 4: የትምህርት አይነቱን ይገልጻል
    subject_label = q.get('subject', 'ጠቅላላ እውቀት')
    msg = await context.bot.send_poll(
        context.job.chat_id, 
        f"[{subject_label}] {q['q']}", 
        q['o'], is_anonymous=False, 
        type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
    )
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], context.job.chat_id))
        await db.commit()

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user_name = ans.user.first_name

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
            # Rule 3 & 6: ቀድሞ የመለሰን ማሳወቅ (ጾታ የማይለይ)
            await context.bot.send_message(chat_id, f"🏆 እንኳን ደስ አለህ/ሽ {user_name}! ቀድመህ/ሽ በትክክል በመመለስህ/ሽ 8 ነጥብ አግኝተሃል/ሻል።")
        else:
            points = 4
    else:
        points = 1.5

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, user_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMANDS ---
async def start2_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if user_id not in ADMIN_IDS:
        # Rule 1 & 6: የእገዳ መልእክት (ጾታ የማይለይ)
        until = (datetime.now() + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user_id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {update.effective_user.first_name} የአድሚን ትዕዛዝ በመንካትህ/ሽ 3.17 ነጥብ ተቀንሶብሃል/ሻል፤ ለ 17 ደቂቃም ታግደሃል/ሻል።")
        return

    # Rule 5: ውድድር መጀመሩን ማብሰር
    context.job_queue.run_repeating(send_quiz, 240, 1, chat_id, name=str(chat_id))
    await update.message.reply_text("📣 ውድድሩ በይፋ ተጀምሯል! በየ 4 ደቂቃው በረንደም ጥያቄዎች ይቀርባሉ። መልካም ዕድል!")

async def rank2_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule 2: ደረጃ ለማየት ብቻ (ውድድሩን አያቆምም)
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    res = "📊 ወቅታዊ የደረጃ ሰንጠረዥ፦\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def stop2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for job in jobs: job.schedule_removal()
    await update.message.reply_text("🏁 ውድድሩ በቆይታው ተጠናቋል። ስለተሳተፋችሁ እናመሰግናለን!")
    await rank2_view(update, context)

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start2", start2_group))
    application.add_handler(CommandHandler("rank2", rank2_view))
    application.add_handler(CommandHandler("stop2", stop2_cmd))
    application.add_handler(CommandHandler(["History_srm2", "Geography_srm2", "Mathematics_srm2", "English_srm"], start2_group))
    
    application.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
