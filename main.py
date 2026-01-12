import os
import logging
import asyncio
import random
import aiosqlite
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters

# --- Render እንዳይዘጋ (Flask Server) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- CONFIGURATION ---
# ቶከኑን ከ Render Environment Variable ያነባል (ለደህንነትና ለስህተት መፍትሄ)
TOKEN = os.getenv("BOT_TOKEN", "8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE")
ADMIN_IDS = [7231324244, 8394878208]

# --- DATABASE SETUP ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
                            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
                            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner TEXT, explanation TEXT)''')
        await db.commit()

async def update_user_points(user_id, points, username):
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- QUIZ LOGIC ---
async def start_quiz(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    # በየሳብጀክቱ የተከፋፈሉ ጥያቄዎች (Rule 16)
    questions = [
        {"q": "[Maths] (10 x 10) + 50 ስንት ነው?", "o": ["100", "150", "200"], "c": 1, "e": "10x10=100 ነው። 100+50 ደግሞ 150 ይሆናል።"},
        {"q": "[Biology] የሰው ልጅ ስንት ኩላሊት አለው?", "o": ["1", "2", "3"], "c": 1, "e": "ጤነኛ ሰው 2 ኩላሊቶች አሉት።"},
        {"q": "[History] አድዋ የት ሀገር ይገኛል?", "o": ["ኢትዮጵያ", "ሱዳን", "ኬንያ"], "c": 0, "e": "አድዋ በሰሜን ኢትዮጵያ በትግራይ ክልል ይገኛል።"}
    ]
    q = random.choice(questions)
    
    # Rule 14 & 18: ማብራሪያ (Explanation)
    message = await context.bot.send_poll(
        job.chat_id, q['q'], q['o'], 
        is_anonymous=False, type=Poll.QUIZ, correct_option_id=q['c'],
        explanation=q['e'] 
    )
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, NULL, ?)", (message.poll.id, q['c'], job.chat_id, q['e']))
        await db.commit()

async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user_id
    user_name = update.effective_user.first_name if update.effective_user else "ተሳታፊ"
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id, explanation FROM active_polls WHERE poll_id = ?", (answer.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_winner, chat_id, explanation = poll_data

    if answer.option_ids[0] == correct_idx:
        if first_winner is None: # Rule 2 & 15: ቀድሞ የመለሰ
            await update_user_points(user_id, 8, user_name)
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (user_name, answer.poll_id))
                await db.commit()
            await context.bot.send_message(chat_id, f"🥇 {user_name} ቀድሞ በመመለስ 8 ነጥብ አገኘ! 🎆\n💡 ማብራሪያ፡ {explanation}")
        else: # Rule 3: ዘግይቶ የመለሰ
            await update_user_points(user_id, 4, user_name)
    else: # Rule 4: ለተሳሳተ
        await update_user_points(user_id, 1.5, user_name)

# --- ADMIN COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    chat_id = update.effective_chat.id
    # Rule 1: በየ 4 ደቂቃው (240 ሰከንድ)
    context.job_queue.run_repeating(start_quiz, interval=240, first=1, chat_id=chat_id, name=str(chat_id))
    await update.message.reply_text("<b>🚀 ውድድሩ ተጀመረ! (በየ 4 ደቂቃው)</b>", parse_mode="HTML")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs: job.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            winners = await cursor.fetchall()
    
    # Rule 5 & 12: አሸናፊዎችና ዋንጫዎች
    text = "<b>🏁 ውድድሩ አብቅቷል!</b>\n\n"
    for i, (name, pts) in enumerate(winners):
        medal = "🥇 (3 የወርቅ ዋንጫ)" if i==0 else "🥈 (2 የብር ዋንጫ)" if i==1 else "🥉 (1 የነሐስ ሽልማት)" if i==2 else f"{i+1}."
        text += f"{medal} {name}: {pts} ነጥብ\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def clear_rank2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = 0")
        await db.commit()
    await update.message.reply_text("🧹 ነጥብ በሙሉ ተሰርዟል! (Rule 10)")

# --- MAIN RUNNER ---
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("clear_rank2", clear_rank2))
    application.add_handler(PollAnswerHandler(receive_poll_answer))
    
    keep_alive()
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
