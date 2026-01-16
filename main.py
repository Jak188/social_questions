import os, json, asyncio, random, aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters

# --- Flask Server (ለቦቱ ህይወት መስጫ) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online and Perfect!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 

# --- Database Setup ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, timestamp TEXT)''')
        await db.commit()

async def get_user(uid):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (uid,)) as c: return await c.fetchone()

# --- Quiz Engine ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            subject = job.data.get('subject')
            questions = [q for q in all_q if q.get('subject', '').lower() == subject.lower()] if subject else all_q
            if not questions: return
            q = random.choice(questions)
            msg = await context.bot.send_poll(job.chat_id, f"[{q.get('subject', 'General')}] {q['q']}", q['o'], 
                is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', ''))
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (?, ?, ?)", (msg.poll.id, int(q['c']), job.chat_id))
                await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user = await get_user(ans.user.id)
    if not user or user[3] != 'approved' or user[4] == 1: return
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_data = await c.fetchone()
        if not poll_data: return
        
        is_correct = (ans.option_ids[0] == poll_data[0])
        points = 8 if (is_correct and poll_data[1] == 0) else (4 if is_correct else 1.5)
        
        if is_correct and poll_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
        
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp) VALUES (?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", datetime.now().strftime("%H:%M:%S")))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        await db.commit()

# --- Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    if u_data and u_data[4] == 1: return

    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        # አንተ የፈለግከው የአድሚን ማሳወቂያ ዲዛይን
        reg_msg = (f"👤 አዲስ ተመዝጋቢ:\n"
                   f"ስም: {user.first_name}\n"
                   f"ID: {user.id}\n"
                   f"ለማጽደቅ: `/approve {user.id}`\n\n\n"
                   f"ለመከልከል: `/anapprove {user.id}`")
        for admin in ADMIN_IDS: await context.bot.send_message(admin, reg_msg)
        await update.message.reply_text("ውድ ተማሪ የምዝገባ ጥያቄዎ ለአድሚን ደርሷል።")
        return

    if u_data[3] != 'approved':
        await update.message.reply_text("አድሚኑ እስኪያጸድቅ ይጠብቁ።")
        return

    # ግሩፕ ላይ አድሚን ያልሆነ ሰው ለማዘዝ ቢሞክር (የ17 ደቂቃ ቅጣት)
    if user.id not in ADMIN_IDS and chat.type != "private":
        mute_limit = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_limit, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል፤ ለ17 ደቂቃም ታግደሃል።")
        return

    # ውድድር ማስጀመሪያ
    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}
    subject = subject_map.get(cmd)

    # የቆየ ስራን ማቆም (ለአዲስ ውድድር)
    old_jobs = context.job_queue.get_jobs_by_name(str(chat.id))
    for j in old_jobs: j.schedule_removal()

    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, 
                                    data={'subject': subject, 'starter': user.first_name, 'time': datetime.now().strftime("%H:%M")}, 
                                    name=str(chat.id))
    await update.message.reply_text(f"🚀 የ{subject if subject else 'General'} ውድድር ተጀመረ!")
    
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"📢 ውድድር ተጀመረ!\nበ: {user.first_name}\nቦታ: {chat.title if chat.title else 'Private'}")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    full_cmd = update.message.text.split()
    cmd = full_cmd[0][1:].lower()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "stop2":
            chat_id = str(update.effective_chat.id)
            jobs = context.job_queue.get_jobs_by_name(chat_id)
            if jobs:
                for j in jobs: j.schedule_removal()
                await update.message.reply_text("🏁 ውድድሩ በአድሚን ትዕዛዝ ቆሟል።")
            else:
                await update.message.reply_text("❌ የሚቆም ንቁ ውድድር የለም።")

        elif cmd == "keep2":
            jobs = context.job_queue.jobs()
            if not jobs:
                await update.message.reply_text("ምንም ንቁ ውድድር የለም።")
                return
            await update.message.reply_text("🟢 ንቁ ውድድሮች ዝርዝር (በነጠላ)፦")
            for j in jobs:
                msg = f"📍 ID: `{j.name}`\n👤 በ: {j.data.get('starter')}\n⌚ ሰዓት: {j.data.get('time')}"
                await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown')

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username, points FROM users ORDER BY points DESC") as c:
                rows = await c.fetchall()
                if not rows:
                    await update.message.reply_text("ምንም ተመዝጋቢ የለም።")
                    return
                await update.message.reply_text("📌 የተመዝጋቢዎች ዝርዝር (በነጠላ)፦")
                for r in rows:
                    msg = f"👤 ስም: {r[1]}\n🆔 ID: `{r[0]}`\n📊 ነጥብ: {r[2]} pts"
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown')

        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 15") as c:
                rows = await c.fetchall()
                if rows:
                    res = "📜 እንቅስቃሴዎች:\n" + "\n".join([f"{r[2]} | {r[0]} {r[1]}" for r in rows])
                    await update.message.reply_text(res)
                else: await update.message.reply_text("Log ባዶ ነው")

        elif cmd == "approve" and len(full_cmd) > 1:
            uid = int(full_cmd[1])
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "✅ እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
            await update.message.reply_text(f"ተጠቃሚ {uid} ጸድቋል።")

# --- Main ---
def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "stop2", "keep2", "log", "pin"], admin_cmd))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    print("Bot is ready and running!")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
