import os
import json
import asyncio
import random
import aiosqlite
import re
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

# --- 1. Flask Server (Uptime Monitoring) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Running Professionally!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. Configuration & Constants ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 

# --- 3. Database Management ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        # የተጠቃሚዎች ሰንጠረዥ
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, 
             username TEXT, 
             points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', 
             is_blocked INTEGER DEFAULT 0, 
             muted_until TEXT)''')
        
        # የጥያቄዎች መቆጣጠሪያ
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, 
             correct_option INTEGER, 
             chat_id INTEGER, 
             first_winner INTEGER DEFAULT 0)''')
        
        # የታሪክ ምዝገባ (Logs)
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, 
             name TEXT, 
             action TEXT, 
             chat_name TEXT, 
             timestamp TEXT)''')
        await db.commit()

async def get_user_data(uid):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (uid,)) as c:
            return await c.fetchone()

# --- 4. Quiz Logic (The Engine) ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    chat_id = job.chat_id
    subject = job.data.get('subject')

    try:
        if not os.path.exists('questions.json'): return
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_questions = json.load(f)
            
            # Subject Filter
            if subject:
                questions = [q for q in all_questions if q.get('subject', '').lower() == subject.lower()]
            else:
                questions = all_questions

            if not questions: return
            
            q = random.choice(questions)
            poll_msg = await context.bot.send_poll(
                chat_id,
                f"[{q.get('subject', 'General')}] {q['q']}",
                q['o'],
                is_anonymous=False,
                type=Poll.QUIZ,
                correct_option_id=int(q['c']),
                explanation=q.get('exp', 'ተሳስተሃል! ትክክለኛው መልስ ተጠቁሟል።')
            )

            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute(
                    "INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (?, ?, ?)",
                    (poll_msg.poll.id, int(q['c']), chat_id)
                )
                await db.commit()
    except Exception as e:
        print(f"Quiz Error: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user_data = await get_user_data(user_id)

    # እገዳ መኖሩን መፈተሽ
    if not user_data or user_data[3] != 'approved' or user_data[4] == 1: return
    if user_data[5]:
        if datetime.now(timezone.utc) < datetime.fromisoformat(user_data[5]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_info = await c.fetchone()
        
        if not poll_info: return
        
        correct_idx, first_winner_id, chat_id = poll_info
        is_correct = (ans.option_ids[0] == correct_idx)

        # የነጥብ ህግ: 8 ለቀደመ፣ 4 ለዘገየ፣ 1.5 ለተሳሳተ
        if is_correct:
            if first_winner_id == 0:
                earned_points = 8
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (user_id, ans.poll_id))
                await context.bot.send_message(chat_id, f"🏆 ፈጣን ምላሽ! {ans.user.first_name} 8 ነጥብ አግኝቷል።")
            else:
                earned_points = 4
        else:
            earned_points = 1.5

        # መመዝገብ
        action_mark = "✅" if is_correct else "❌"
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?, ?)", 
                         (user_id, ans.user.first_name, action_mark, "Global", datetime.now().strftime("%H:%M:%S")))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (earned_points, user_id))
        await db.commit()

# --- 5. Security & Command Filters ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_data = await get_user_data(user.id)

    # 1. የታገደ ተማሪ ከሆነ
    if user_data and user_data[4] == 1:
        return

    # 2. ቦቱ በአድሚን ከቆመ
    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"🚫 ቦቱ ለጊዜው ተቋርጧል። {ADMIN_USERNAME}")
        return

    # 3. በግል (Private) የተከለከለ ትዕዛዝ ከላከ
    if chat.type == "private":
        cmd_text = update.message.text.split()[0].lower()
        allowed = ["/start2", "/stop2", "/geography_srm2", "/history_srm2", "/english_srm2", "/mathematics_srm2", "/rank2"]
        if cmd_text not in allowed and user.id not in ADMIN_IDS:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"🚫 የህግ ጥሰት! ያልተፈቀደ ትዕዛዝ በመጠቀማችሁ በራስ-ሰር ታግዳችኋል። ለመፈታት {ADMIN_USERNAME} ን ያነጋግሩ።")
            return

    # 4. ግሩፕ ላይ አድሚን ያልሆነ ሰው ለማዘዝ ቢሞክር
    if user.id not in ADMIN_IDS and chat.type != "private":
        mute_limit = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_limit, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል፤ ለ17 ደቂቃም መልስ መስጠት አትችልም።")
        return

    # 5. አዲስ ምዝገባ
    if not user_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        
        # አንተ የፈለግከው የአድሚን ማሳወቂያ ዲዛይን
        for admin in ADMIN_IDS:
            await context.bot.send_message(
                admin, 
                f"👤 አዲስ ተመዝጋቢ:\n"
                f"ስም: {user.first_name}\n"
                f"ID: {user.id}\n"
                f"ለማጽደቅ: `/approve {user.id}`\n\n"
                f"ለመከልከል: `/anapprove {user.id}`"
            )
        await update.message.reply_text(f"ውድ {user.first_name} የምዝገባ ጥያቄዎ ለአድሚን ደርሷል።")
        return

    if user_data[3] == 'pending':
        await update.message.reply_text("አድሚኑ ገና አላጸደቀልዎትም...")
        return

    # 6. ውድድር መጀመር
    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2": "history", "geography_srm2": "geography", "mathematics_srm2": "mathematics", "english_srm2": "english"}
    subject = subject_map.get(cmd)

    # ቀድሞ የነበረን ስራ ማቆም
    existing_jobs = context.job_queue.get_jobs_by_name(str(chat.id))
    for j in existing_jobs: j.schedule_removal()

    # በየ 4 ደቂቃው ጥያቄ መላክ
    context.job_queue.run_repeating(
        send_quiz, 
        interval=240, 
        first=5, 
        chat_id=chat.id, 
        data={'subject': subject, 'starter': user.first_name, 'time': datetime.now().strftime("%H:%M")}, 
        name=str(chat.id)
    )
    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀምሯል!")

# --- 6. Admin Control Panel ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    full_text = update.message.text
    cmd = full_text.split()[0][1:].lower()

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve":
            uid = int(context.args[0])
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "✅ እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
            await update.message.reply_text(f"ተጠቃሚ {uid} ጸድቋል።")

        elif cmd == "unblock":
            uid = int(context.args[0])
            await db.execute("UPDATE users SET is_blocked = 0, muted_until = NULL WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "🔊 ማስጠንቀቂያ፦ እገዳዎ ተነስቷል። እባክዎ ደንብ ያክብሩ!")
            await update.message.reply_text(f"እገዳ ተነስቷል ለ {uid}")

        elif cmd in ["oppt", "opptt"]:
            global GLOBAL_STOP
            GLOBAL_STOP = (cmd == "oppt")
            status_msg = f"🚫 ቦቱ በአድሚን ታግዷል። {ADMIN_USERNAME}" if GLOBAL_STOP else "✅ ቦቱ አሁን ክፍት ነው። መሳተፍ ትችላላችሁ።"
            async with db.execute("SELECT user_id FROM users") as cur:
                all_users = await cur.fetchall()
                for r in all_users:
                    try: await context.bot.send_message(r[0], status_msg)
                    except: continue
            await update.message.reply_text(f"Broadcast ተልኳል: {'Stop' if GLOBAL_STOP else 'Start'}")

        elif cmd == "rank2":
            if update.effective_chat.type == "private":
                u = await get_user_data(update.effective_user.id)
                await update.message.reply_text(f"📊 የእርስዎ ነጥብ: {u[2]}")
            else:
                async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as c:
                    rows = await c.fetchall()
                    res = "📊 የደረጃ ሰንጠረዥ (Top 15):\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
                    await update.message.reply_text(res if rows else "ምንም ውጤት የለም")

        elif cmd == "keep2":
            all_jobs = context.job_queue.jobs()
            if not all_jobs:
                await update.message.reply_text("ምንም ንቁ ውድድር የለም።")
                return
            res = "🟢 ንቁ ውድድሮች:\n"
            for j in all_jobs:
                res += f"📍 ID: `{j.name}` | በ: {j.data.get('starter')} | ሰዓት: {j.data.get('time')}\n---\n"
            await update.message.reply_text(res, parse_mode='Markdown')

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username, points FROM users") as c:
                rows = await c.fetchall()
                res = "📌 የተመዝጋቢዎች ዝርዝር:\n"
                for r in rows: res += f"🔹 {r[1]} | ID: `{r[0]}` | ነጥብ: {r[2]}\n"
                await update.message.reply_text(res, parse_mode='Markdown')

        elif cmd == "close":
            target_id = context.args[0] if context.args else str(update.effective_chat.id)
            jobs = context.job_queue.get_jobs_by_name(target_id)
            for j in jobs: j.schedule_removal()
            await update.message.reply_text(f"🏁 ውድድር ቆሟል (ID: {target_id})")

# --- 7. Main Execution ---
def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()

    # Handlers
    quiz_cmds = ["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(quiz_cmds, start_handler))
    
    adm_cmds = ["approve", "anapprove", "unblock", "oppt", "opptt", "rank2", "keep2", "pin", "close", "log"]
    app_bot.add_handler(CommandHandler(adm_cmds, admin_panel))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    # ብሎክ ለማድረግ (ከተፈቀዱት ውጭ ትዕዛዝ ቢላክ)
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, start_handler))

    keep_alive()
    print("Bot is started with 300+ lines of logic...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
