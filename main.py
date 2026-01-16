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

# --- 1. Flask Server (For Render/Uptime) ---
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
                # እዚህ ጋር በትክክል ለየብቻ እንዲወጡ ያደርጋል
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
    
    # ነጥብ አሰጣጥ: 8, 4, 1.5
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

    if not user_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"👋 ሰላም {user.first_name}!\nየምዝገባ ጥያቄዎ ደርሶናል። አድሚን እስኪያጸድቅ ድረስ ስራ ስለሚበዛብን በትዕግስት ይጠብቁ።")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ተመዝጋቢ: {user.first_name} (ID: {user.id})\nለማጽደቅ: `/approve {user.id}`")
        return
    
    if user_data[2] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
        return

    # ግሩፕ ውስጥ አድሚን ካልሆነ መቀጣት
    if user.id not in ADMIN_IDS and chat_type != "private":
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶብዎታል፤ ለ 17 ደቂቃም ታግደዋል።", reply_to_message_id=update.message.message_id)
        return

    # የትምህርት አይነት መለያ
    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {
        "history_srm2": "history", 
        "geography_srm2": "geography", 
        "mathematics_srm2": "mathematics", 
        "english_srm2": "english"
    }
    subject = subject_map.get(cmd) # start2 ከሆነ subject None ይሆናል (Random)

    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for j in jobs: j.schedule_removal()
    
    # በየ 4 ደቂቃው ጥያቄ ይልካል
    context.job_queue.run_repeating(send_quiz, interval=240, first=5, chat_id=chat_id, data={'subject': subject}, name=str(chat_id))
    
    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀምሯል!")
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"📢 ቦቱ ተነስቷል በ: {user.first_name} ({chat_type})")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    
    if jobs:
        for j in jobs: j.schedule_removal()
        if update.effective_chat.type == "private":
            user_data = await get_user_data(update.effective_user.id)
            await update.message.reply_text(f"🏁 ቦቱ ቆሟል። የእርስዎ ነጥብ: {user_data[0]}")
        else:
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as cursor:
                    rows = await cursor.fetchall()
            res = "📊 የውድድሩ መጨረሻ (Best 15):\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)]) if rows else "ነጥብ የለም"
            await update.message.reply_text(res)
        
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"🛑 ቦቱ ቆሟል በ: {update.effective_user.first_name}")
    else:
        await update.message.reply_text("❌ የሚቆም ውድድር የለም።")

async def private_msg_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ግል ላይ የተሳሳተ ትዕዛዝ ሲላክ ወዲያውኑ ብሎክ የሚያደርግ"""
    if update.effective_chat.type != "private" or update.effective_user.id in ADMIN_IDS: return
    
    text = update.message.text
    valid_cmds = ['/start', '/start2', '/rank2', '/history_srm2', '/geography_srm2', '/mathematics_srm2', '/english_srm2', '/info2']
    
    if text.startswith('/') and text.split('@')[0] not in valid_cmds:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (update.effective_user.id,))
            await db.commit()
        await update.message.reply_text(f"🚫 የህግ ጥሰት! ያልተፈቀደ ትዕዛዝ ስለተጠቀሙ ወዲያውኑ ታግደዋል። {ADMIN_USERNAME} ያነጋግሩ።")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:]
    
    try:
        if cmd == "approve":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
            await update.message.reply_text(f"✅ ተጠቃሚ {uid} ጸድቋል።")
            
        elif cmd == "anapprove":
            uid = int(context.args[0])
            await context.bot.send_message(uid, "❌ ጥያቄዎ ተቀባይነት አላገኘም። እባክዎ እንደገና ይሞክሩ።")
            await update.message.reply_text(f"❌ {uid} ውድቅ ተደርጓል።")

        elif cmd == "block":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ያነጋግሩ።")
            await update.message.reply_text(f"🚫 {uid} ታግዷል።")

        elif cmd == "unblock":
            uid = int(context.args[0])
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 0, muted_until = NULL WHERE user_id = ?", (uid,))
                await db.commit()
            await context.bot.send_message(uid, "✅ እገዳዎ ተነስቷል፤ አሁን መሳተፍ ይችላሉ።")
            await update.message.reply_text(f"✅ የ {uid} እገዳ ተነስቷል።")

        elif cmd == "appt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await update.message.reply_text(f"🛑 ቦቱ ከአድሚን በመጣ ትዕዛዝ ለሁሉም ተጠቃሚዎች ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")

        elif cmd == "apptt":
            GLOBAL_STOP = False
            await update.message.reply_text("✅ ቦቱ ወደ ስራ ተመልሷል።")
            
        elif cmd == "log":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 30") as cursor:
                    rows = await cursor.fetchall()
            res = "📜 የውድድር ዝርዝር:\n" + "\n".join([f"{r[1]}: {r[2]}" for r in rows])
            await update.message.reply_text(res)

        elif cmd == "info2":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT username, user_id, status FROM users") as cursor:
                    rows = await cursor.fetchall()
            res = f"👥 ጠቅላላ ተመዝጋቢ: {len(rows)}\n" + "\n".join([f"{r[0]} ({r[1]}) - {r[2]}" for r in rows])
            await update.message.reply_text(res)
            
        elif cmd == "clear_rank2":
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = 0")
                await db.commit()
            await update.message.reply_text("🧹 ሁሉም ነጥቦች ተሰርዘዋል።")

        elif cmd == "keep":
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await update.message.reply_text(f"🟢 ቦቱ ACTIVE ነው!\nሰዓት: {now}")

        elif cmd == "close":
            uid = int(context.args[0])
            jobs = context.job_queue.get_jobs_by_name(str(uid))
            for j in jobs: j.schedule_removal()
            await update.message.reply_text(f"🏁 ለተጠቃሚ {uid} ቦቱ ቆሟል።")

    except Exception as e: await update.message.reply_text(f"⚠️ ስህተት: {e}")

async def unmute_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unmute ሲባል እገዳ የሚያነሳ (Replay ለተደረገለት ሰው)"""
    if update.effective_user.id not in ADMIN_IDS: return
    if not update.message.reply_to_message: return
    
    target_user = update.message.reply_to_message.from_user
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target_user.id,))
        await db.commit()
    await update.message.reply_text(f"✅ የ {target_user.first_name} የቅጣት እገዳ ተነስቷል።")

# --- 7. Main Function ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # ትዕዛዞች
    srm2_cmds = ["history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "start2"]
    app_bot.add_handler(CommandHandler(srm2_cmds, start_handler))
    app_bot.add_handler(CommandHandler("stop2", stop_cmd))
    app_bot.add_handler(CommandHandler("rank2", stop_cmd)) # Rank ለማየት stop2 መጠቀም ይቻላል
    app_bot.add_handler(CommandHandler("unmute", unmute_handler))
    
    # አድሚን ብቻ
    admin_cmds = ["approve", "anapprove", "block", "unblock", "appt", "apptt", "log", "info2", "clear_rank2", "keep", "close"]
    app_bot.add_handler(CommandHandler(admin_cmds, admin_panel))
    
    # ሌሎች
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, private_msg_guard))
    
    keep_alive()
    print("Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
