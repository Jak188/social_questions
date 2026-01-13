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

# --- Flask Server (Uptime) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIGURATION ---
TOKEN = "8256328585:AAHTvHxxChdIohofHdDcrOeTN1iEbWcx9QI"
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE SETUP ---
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
            data = json.load(f)
            return data
    except Exception as e:
        print(f"Error loading questions: {e}")
        return []

# --- QUIZ LOGIC ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    questions = load_all_questions()
    if not questions:
        print("No questions found in JSON!")
        return
    
    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            context.job.chat_id, 
            q['q'], 
            q['o'], 
            is_anonymous=False, 
            type=Poll.QUIZ, 
            correct_option_id=q['c'], 
            explanation=q.get('exp', 'ትክክለኛውን መልስ ስለመረጥክ እናመሰግናለን!')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], context.job.chat_id))
            await db.commit()
    except Exception as e:
        print(f"Failed to send poll: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] and datetime.now() < datetime.fromisoformat(row[0]):
                return 

        async with db.execute("SELECT correct_option, first_done FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done = poll_data
    points = 0
    
    if ans.option_ids[0] == correct_idx:
        if first_done == 0:
            points = 8  # ቀድሞ ለመለሰ
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
                await db.commit()
        else:
            points = 4  # ዘግይቶ ለመለሰ
    else:
        points = 1.5 # ለተሳሳተ

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, ans.user.first_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMANDS ---
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private":
        if user.id in ADMIN_IDS:
            await update.message.reply_text("ሰላም አድሚን! ስራህን መቀጠል ትችላለህ።")
            return
        
        # በግል ሲሆን ምዝገባ ብቻ ይጠይቃል (ቅጣት የለም)
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.first_name))
            await db.commit()
        
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ምዝገባ ጥያቄ:\nስም: {user.first_name}\nID: `{user.id}`\nለማጽደቅ: `/approve {user.id}`")
        await update.message.reply_text("የምዝገባ ጥያቄህ ለአድሚን ተልኳል፤ ሲፈቀድልህ ጥያቄዎች ይደርሱሃል።")

async def start2_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # አድሚን ካልሆነና በግሩፕ ውስጥ ትዕዛዝ ከሰጠ ይቀጣል
    if user_id not in ADMIN_IDS:
        if update.effective_chat.type != "private":
            until = (datetime.now() + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user_id))
                await db.commit()
            await update.message.reply_text(f"⚠️ {update.effective_user.first_name} የአድሚን ትዕዛዝ ስለነካህ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደሃል!")
        return

    # ውድድሩን በየ 4 ደቂቃው ያስጀምራል
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, name=str(chat_id))
    await update.message.reply_text("🚀 ውድድሩ በየ 4 ደቂቃው በረንደም ጥያቄዎችን መላክ ጀምሯል!")

async def stop2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
    for job in jobs: job.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    
    res = "🏁 ውድድሩ ቆሟል!\n🏆 የደረጃ ሰንጠረዥ፡\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} ነጥብ" for i, r in enumerate(rows)])
    await update.message.reply_text(res)

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = int(context.args[0])
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
        # ለተመዘገበው ሰው በግል ጥያቄ መላክ ይጀምራል
        context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=target_id, name=str(target_id))
        await update.message.reply_text(f"✅ ተጠቃሚ {target_id} ጸድቋል፤ ጥያቄዎች ይላኩለታል።")
    except:
        await update.message.reply_text("እባክህ ID ቁጥሩን ጨምር።")

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler("start", start_private))
    app_bot.add_handler(CommandHandler("start2", start2_group))
    app_bot.add_handler(CommandHandler("approve", approve))
    app_bot.add_handler(CommandHandler("stop2", stop2))
    app_bot.add_handler(CommandHandler("rank2", lambda u, c: stop2(u, c)))
    app_bot.add_handler(CommandHandler(["History_srm2", "Geography_srm2", "Mathematics_srm2", "English_srm"], start2_group))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
