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
TOKEN = os.getenv("BOT_TOKEN", "8256328585:AAHTvHxxChdIohofHdDcrOeTN1iEbWcx9QI")
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
async def is_approved_or_admin(user_id, chat_type):
    if user_id in ADMIN_IDS: return True
    if chat_type != "private": return True # ግሩፕ ላይ ምዝገባ አያስፈልግም
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT status FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row and row[0] == 'approved'

# --- QUIZ LOGIC ---
async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    
    # እገዳ መኖሩን ቼክ ማድረግ
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
        points = 8 if first_done == 0 else 4
        if first_done == 0:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
                await db.commit()
    else: points = 1.5

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, ans.user.first_name))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.commit()

# --- COMMAND HANDLERS ---
async def start2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("እንኳን ደህና መጡ ጌታዬ! ትዕዛዝዎን ለመቀበል ዝግጁ ነኝ።")
        return

    chat_type = update.effective_chat.type
    if chat_type == "private":
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, update.effective_user.first_name))
            await db.commit()
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ምዝገባ:\nስም: {update.effective_user.first_name}\nID: `{user_id}`\nለማጽደቅ: `/approve {user_id}`")
        await update.message.reply_text("ምዝገባዎ ለባለቤቱ ተልኳል፤ ሲፈቀድልዎ በግል ማውራት ይችላሉ።")

async def handle_violation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS: return # አድሚን አይቀጣም

    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user.id))
        await db.commit()
    await update.message.reply_text(f"⚠️ {user.first_name} በአድሚን ትዕዛዝ ጣልቃ በመግባትህ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደሃል!")

# ... (ሌሎች ኮማንዶች approve, stop2, mute2, send_quiz ቀደም ብለው እንደተላኩት ይቀጥላሉ) ...

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler("start2", start2_cmd))
    # አድሚን ያልሆነ ሰው እነዚህን ትዕዛዞች ቢነካ ይቀጣል
    app_bot.add_handler(MessageHandler(filters.Regex(r'^\/(approve|stop2|mute2|un_mute2|clear_rank2|.*_srm2)') & ~filters.User(ADMIN_IDS), handle_violation))
    
    # መደበኛ የአድሚን ትዕዛዞች
    from telegram.ext import PollAnswerHandler
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    # ... (ሌሎች Handlers እዚህ ይጨመሩ) ...

    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
