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
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 

# --- 3. Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, username TEXT, action TEXT, timestamp TEXT)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        if not os.path.exists('questions.json'): return []
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject:
                return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except Exception: return []

async def get_user_data(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT points, muted_until, is_blocked, status, username FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Quiz Logic ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    chat_id = job.chat_id
    subject = job.data.get('subject')
    questions = load_questions(subject)
    
    if not questions:
        await context.bot.send_message(chat_id, f"❌ ለ '{subject if subject else 'Random'}' የሚሆኑ ጥያቄዎች አልተገኙም!")
        return

    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            chat_id, f"[{q.get('subject', 'Random')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, int(q['c']), chat_id))
            await db.commit()
    except Exception as e: print(f"Poll Error: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user = await get_user_data(user_id)
    
    if not user or user[2] == 1 or user[3] != 'approved': return 
    if user[1] and datetime.now(timezone.utc) < datetime.fromisoformat(user[1]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_done, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    correct_idx, first_done, chat_id = poll_data
    is_correct = ans.option_ids[0] == correct_idx
    points = 8 if (is_correct and first_done == 0) else (4 if is_correct else 1.5)

    if is_correct and first_done == 0:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
            await db.commit()
        await context.bot.send_message(chat_id, f"🏆 እንኳን ደስ አለዎት {ans.user.first_name}! ቀድመው በመመለስዎ 8 ነጥብ አግኝተዋል።")

    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?)", (user_id, ans.user.first_name, f"Mels: {'Tikkil' if is_correct else 'Sihitet'}", datetime.now().isoformat()))
        await db.commit()

# --- 6. Command Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    user_data = await get_user_data(user.id)

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"🚫 ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
        return

    # 1 & 3: የምዝገባ ሁኔታን መፈተሽ
    if not user_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"👋 ሰላም {user.first_name}!\nየምዝገባ ጥያቄዎ ደርሶናል። አድሚን እስኪያጸድቅ ድረስ ስራ ስለሚበዛብን በትዕግስት ይጠብቁ።")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ተመዝጋቢ: {user.first_name} (ID: {user.id})\nለማጽደቅ: /approve {user.id}")
        return
    
    if user_data[3] == 'pending':
        await update.message.reply_text(f"⏳ ጥያቄዎ በሂደት ላይ ነው፤ እባክዎ ትንሽ ይጠብቁ። አድሚን ቢዚ ስለሆነ በትዕግስት ይጠብቁ፤ ተቀባይነት ሲያገኙ እናሳውቅዎታለን። ለበለጠ መረጃ: {ADMIN_USERNAME}")
        return

    if user_data[2] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
        return

    if user.id not in ADMIN_IDS and chat_type != "private":
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶብዎታል፤ ለ 17 ደቂቃም ታግደዋል።", reply_to_message_id=update.message.message_id)
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2": "history", "geography_srm2": "geography", "mathematics_srm2": "mathematics", "english_srm2": "english"}
    subject = subject_map.get(cmd)

    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀምሯል!")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    text = update.message.text.split()
    cmd = text[0][1:]
    
    try:
        if cmd == "approve":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል፤ አሁን መሳተፍ ይችላሉ።")
            await update.message.reply_text(f"✅ ተጠቃሚ {uid} ጸድቋል።")

        elif cmd == "appt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT user_id FROM users") as cursor:
                    users = await cursor.fetchall()
            for u in users:
                try: await context.bot.send_message(u[0], f"🛑 ቦቱ ከአድሚን በመጣ ትዕዛዝ ለሁሉም ተጠቃሚዎች ቆሟል። ለበለጠ መረጃ: {ADMIN_USERNAME}")
                except: pass
            await update.message.reply_text("🛑 ቦቱ በሁሉም ቦታ ቆሟል።")

        elif cmd == "apptt":
            GLOBAL_STOP = False
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT user_id FROM users") as cursor:
                    users = await cursor.fetchall()
            for u in users:
                try: await context.bot.send_message(u[0], f"✅ ቦቱ ወደ ስራ ተመልሷል! አሁን መሳተፍ ትችላላችሁ። ለበለጠ መረጃ: {ADMIN_USERNAME}")
                except: pass
            await update.message.reply_text("✅ ቦቱ ወደ ስራ ተመልሷል።")

        elif cmd == "keep2":
            all_jobs = context.job_queue.jobs()
            if not all_jobs:
                await update.message.reply_text("📭 በአሁኑ ሰዓት የሚሰራ ምንም ውድድር የለም።")
                return
            res = "🟢 አሁን እየሰሩ ያሉ ውድድሮች:\n"
            for j in all_jobs:
                res += f"📍 ID: {j.name} | Subject: {j.data.get('subject', 'Random')}\n"
            await update.message.reply_text(res + "\nለማቆም የሚፈልጉትን መርጠው Replay በማድረግ /close ይበሉ።")

        elif cmd == "close":
            target_id = None
            if update.message.reply_to_message:
                # ከ keep2 መልእክት ላይ ID መፈለግ
                import re
                match = re.search(r"ID: (-?\d+)", update.message.reply_to_message.text)
                if match: target_id = match.group(1)
            
            if not target_id:
                await update.message.reply_text("⚠️ እባክዎ ሊያቆሙት የሚፈልጉትን የ /keep2 ዝርዝር Replay ያድርጉ።")
                return
                
            jobs = context.job_queue.get_jobs_by_name(str(target_id))
            for j in jobs: j.schedule_removal()
            await context.bot.send_message(target_id, f"🏁 የዚህ ግሩፕ/ተጠቃሚ ውድድር በአድሚን ትእዛዝ ቆሟል። ለበለጠ መረጃ: {ADMIN_USERNAME}")
            await update.message.reply_text(f"✅ ለ {target_id} ቦቱ እንዲያቆም ተደርጓል።")

    except Exception as e: await update.message.reply_text(f"⚠️ ስህተት: {e}")

# --- 7. Main Function ---
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    
    app_bot = Application.builder().token(TOKEN).build()
    
    srm2_cmds = ["history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "start2"]
    app_bot.add_handler(CommandHandler(srm2_cmds, start_handler))
    
    admin_cmds = ["approve", "appt", "apptt", "keep2", "close", "block", "unblock", "info2", "clear_rank2"]
    app_bot.add_handler(CommandHandler(admin_cmds, admin_panel))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    
    keep_alive()
    print("Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
