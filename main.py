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

# --- QUIZ ENGINE ---
async def send_random_quiz(context: ContextTypes.DEFAULT_TYPE):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            questions = json.load(f)
        
        if not questions: return
        q = random.choice(questions) # ሁሉንም የትምህርት አይነት ቀላቅሎ ይመርጣል
        
        msg = await context.bot.send_poll(
            context.job.chat_id, q['q'], q['o'], is_anonymous=False, 
            type=Poll.QUIZ, correct_option_id=q['c'], explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, q['c'], context.job.chat_id))
            await db.commit()
    except Exception as e:
        print(f"Error in send_quiz: {e}")

# --- HANDLERS ---
async def group_start2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule: በግሩፕ ውስጥ አድሚኑ /start2 ሲል ውድድር ይቀላቅላል
    if update.effective_user.id not in ADMIN_IDS:
        # አድሚን ካልሆነና ትዕዛዝ ከነካ ይቀጣል (Rule 14)
        await handle_violation(update, context)
        return

    # በየ 4 ደቂቃው (240 ሰከንድ) በዘፈቀደ ጥያቄ መላክ ይጀምራል
    context.job_queue.run_repeating(send_random_quiz, interval=240, first=1, chat_id=update.effective_chat.id, name=str(update.effective_chat.id))
    await update.message.reply_text("🚀 የሁሉም ትምህርቶች ውድድር ተቀላቅሎ በየ 4 ደቂቃው እንዲላክ ተደርጓል!")

async def private_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Rule: በግል /start ሲባል ምዝገባ ይጠይቃል
    user = update.effective_user
    if user.id in ADMIN_IDS:
        await update.message.reply_text("ሰላም አድሚን! ቦቱ በግሩፕም ሆነ በግል ለአንተ ዝግጁ ነው።")
        return

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.first_name))
        await db.commit()

    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"👤 አዲስ የምዝገባ ጥያቄ:\nስም: {user.first_name}\nID: `{user.id}`\nለማጽደቅ: `/approve {user.id}`")
    
    await update.message.reply_text("እንኳን መጡ! ቦቱን በግል ለመጠቀም መጀመሪያ መመዝገብ አለብዎት። ጥያቄዎ ለአድሚን ተልኳል።")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        target_id = context.args[0]
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
        await update.message.reply_text(f"✅ ተጠቃሚ {target_id} ጸድቋል። አሁን ቦቱን በግል መጠቀም ይችላል።")
        await context.bot.send_message(target_id, "🎉 ምዝገባዎ በአድሚን ጸድቋል! አሁን ቦቱን መጠቀም ይችላሉ።")
    except:
        await update.message.reply_text("እባክህ የሰውየውን ID ጨምር።")

async def handle_violation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (until, user.id))
        await db.commit()
    await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደሃል!")

# (ቀሪዎቹ receive_answer እና stop2 ኮዶች እንደነበሩ ይቀጥላሉ...)
# [receive_answer እና stop2 ኮዶችን እዚህ ጋር ይጨምሩ]

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    application = Application.builder().token(TOKEN).build()
    
    # ትዕዛዞች
    application.add_handler(CommandHandler("start2", group_start2)) # በግሩፕ
    application.add_handler(CommandHandler("start", private_start)) # በግል
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("stop2", lambda u, c: None)) # ማቆሚያ (ቀደም ሲል የነበረው)
    
    # አድሚን ትዕዛዝ ጥበቃ
    application.add_handler(MessageHandler(filters.Regex(r'^\/.*2$') & ~filters.User(ADMIN_IDS), handle_violation))
    
    # ነጥብ መቀበያ
    application.add_handler(PollAnswerHandler(lambda u, c: None)) # receive_answer እዚህ ይገባል
    
    keep_alive()
    application.run_polling()

if __name__ == '__main__':
    main()
