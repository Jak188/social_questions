import logging
import asyncio
import sqlite3
import random
import aiosqlite
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters

# --- 1. Render እንዳይዘጋ (Flask Server) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot-u be dehna iyisera new!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- 2. CONFIGURATION ---
TOKEN = "8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE"
ADMIN_IDS = [7231324244, 8394878208]
QUIZ_INTERVAL = 240  # 4 ደቂቃ (Rule 1)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- 3. DATABASE SETUP (Rule 17) ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
                            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER, explanation TEXT)''')
        await db.commit()

# --- 4. ረዳት ተግባራት ---
async def get_user_data(user_id, username="Unknown"):
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        await db.commit()
        async with db.execute("SELECT points, muted_until FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_user_points(user_id, points):
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- 5. የትእዛዝ ተግባራት ---
async def start_quiz(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    # ጥያቄዎች በየሳብጀክቱ (Rule 14, 16, 18)
    questions = [
        {"q": "[Sience] Ye sewenetachin lakay akal manew?", "o": ["Liba", "Gubet", "Samba"], "c": 1, "e": "Gubet (Liver) ye sewenetachin lakay akal new."},
        {"q": "[Maths] 10 x 10 sint new?", "o": ["10", "100", "1000"], "c": 1, "e": "10 be 10 siguba 100 yimetal."},
        {"q": "[History] Ye Ethiopia wana katama manew?", "o": ["Addis Ababa", "Gondar", "Harar"], "c": 0, "e": "Addis Ababa be 1879 be Etege Taytu tameseretech."}
    ]
    q = random.choice(questions)
    
    message = await context.bot.send_poll(
        job.chat_id, q['q'], q['o'], 
        is_anonymous=False, type=Poll.QUIZ, correct_option_id=q['c'],
        explanation=q['e'] # Rule 14, 18 (Explanation)
    )
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, NULL, ?)", (message.poll.id, q['c'], job.chat_id, q['e']))
        await db.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    chat_id = update.effective_chat.id
    # Rule 11 (Supports Multiple Groups) & Rule 13 (Demekmek yale simejemer)
    context.job_queue.run_repeating(start_quiz, interval=QUIZ_INTERVAL, first=1, chat_id=chat_id, name=str(chat_id))
    await update.message.reply_text("<b>🚀 ********** ውድድሩ ተጀምሯል! ********** 🚀\nበየ 4 ደቂቃው ጥያቄ ይቀርባል። መልካም እድል!</b>", parse_mode="HTML")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs: job.schedule_removal()

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            winners = await cursor.fetchall()
    
    # Rule 5, 12, 13 (Stop rankings & Trophies)
    text = "<b>🏁 ********** ውድድሩ አቁሟል! ********** 🏁</b>\n\n"
    text += "<b>🏆 የደረጃ ሰንጠረዥ (Top 10) 🏆</b>\n\n"
    for i, (name, pts) in enumerate(winners):
        medal = f"{i+1}ኛ"
        if i == 0: medal = "🥇 (3 የወርቅ ዋንጫ + 🎆)"
        elif i == 1: medal = "🥈 (2 የብር ዋንጫ)"
        elif i == 2: medal = "🥉 (1 የነሐስ ሽልማት + 🎇)"
        text += f"{medal}. {name} - {pts} ነጥብ\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user_id
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner FROM active_polls WHERE poll_id = ?", (answer.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_winner = poll_data

    if answer.option_ids[0] == correct_idx:
        # Rule 6 (Richit yitekus)
        if first_winner is None:
            await update_user_points(user_id, 8) # Rule 2
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (user_id, answer.poll_id))
                await db.commit()
            await context.bot.send_message(user_id, "🎯 በጣም ጎበዝ! ቀድመህ በመመለስህ 8 ነጥብ አግኝተሃል! 🎆 (Rule 2 & 15)")
        else:
            await update_user_points(user_id, 4) # Rule 3
            await context.bot.send_message(user_id, "✅ ትክክል! ዘግይተህ በመመለስህ 4 ነጥብ አግኝተሃል ። (Rule 3)")
    else:
        await update_user_points(user_id, 1.5) # Rule 4
        await context.bot.send_message(user_id, "❌ ተሳስተሃል፣ ግን ለተሳትፎህ 1.5 ነጥብ ተሰጥቶሃል። (Rule 4)")

async def mute_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    
    points, muted_until = await get_user_data(user.id, user.first_name)
    
    # Rule 7 (Mute for 17 mins if touching admin command)
    if muted_until and datetime.fromisoformat(muted_until) > datetime.now():
        await update.message.delete()
        return

    if update.message.text and any(word in update.message.text.lower() for word in ["/start", "/stop", "/clear_rank2"]):
        if user.id not in ADMIN_IDS:
            until = (datetime.now() + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET muted_until = ? WHERE user_id = ?", (until, user.id))
                await db.commit()
            await update.message.reply_text(f"🚫 {user.first_name} ለአድሚን ትዕዛዝ በመሞከርህ ለ 17 ደቂቃ ታግደሃል! (Rule 7)")

async def un_mute2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return # Rule 8
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target_user.id,))
            await db.commit()
        await update.message.reply_to_message.reply_text(f"⚠️ <b>ከባድ ማስጠንቀቂያ ለ {target_user.first_name}:</b>\nእገዳህ ተነስቷል፤ ድጋሚ ብታጠፋ እርምጃ ይወሰዳል! (Rule 8)", parse_mode="HTML")

async def hoo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username FROM users WHERE muted_until IS NOT NULL") as cursor:
            muted = await cursor.fetchall()
    text = "🚫 <b>የታገዱ ሰዎች (Rule 9):</b>\n" + "\n".join([f"• {m[0]}" for m in muted]) if muted else "የታገደ ሰው የለም።"
    await update.message.reply_text(text, parse_mode="HTML")

async def clear_rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return # Rule 10
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ነጥብ በሙሉ ተሰርዟል! (Rule 10)")

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("stop", stop))
    app_bot.add_handler(CommandHandler("un_mute2", un_mute2))
    app_bot.add_handler(CommandHandler("hoo", hoo))
    app_bot.add_handler(CommandHandler("clear_rank2", clear_rank2))
    app_bot.add_handler(PollAnswerHandler(receive_poll_answer))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mute_logic))
    
    print("Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    keep_alive()
    main()
