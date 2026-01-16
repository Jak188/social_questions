import os, json, asyncio, random, aiosqlite
from datetime import datetime, timedelta, timezone
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

# --- Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 

# --- Database ---
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

# --- Quiz Logic ---
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
    if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_data = await c.fetchone()
        if not poll_data: return
        is_correct = (ans.option_ids[0] == poll_data[0])
        points = 8 if (is_correct and poll_data[1] == 0) else (4 if is_correct else 1.5)
        if is_correct and poll_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
        
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?)", (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", datetime.now().strftime("%H:%M:%S")))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        await db.commit()

# --- Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    if u_data and u_data[4] == 1: return

    # Private Command Filter
    if chat.type == "private":
        cmd = update.message.text.split()[0].lower()
        allowed = ["/start2", "/stop2", "/geography_srm2", "/history_srm2", "/english_srm2", "/mathematics_srm2"]
        if cmd not in allowed and user.id not in ADMIN_IDS:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"🚫 የህግ ጥሰት! የታገዱ ሲሆን እገዳው እንዲነሳ {ADMIN_USERNAME} ን ጠይቁ።")
            return

    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        # አንተ የፈለግከው የአድሚን ማሳወቂያ ዲዛይን
        msg = (f"👤 አዲስ ተመዝጋቢ:\n"
               f"ስም: {user.first_name}\n"
               f"ID: {user.id}\n"
               f"ለማጽደቅ: `/approve {user.id}`\n\n\n"
               f"ለመከልከል: `/anapprove {user.id}`")
        for admin in ADMIN_IDS: await context.bot.send_message(admin, msg)
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ ደርሶናል።")
        return

    if u_data[3] == 'pending':
        await update.message.reply_text("አድሚኑ እስኪያጸድቅ ይጠብቁ።")
        return

    # Start Quiz
    cmd = update.message.text.split('@')[0][1:].lower()
    subject = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}.get(cmd)
    
    # አድሚን ላልሆነ ግሩፕ ውስጥ ቅጣት
    if user.id not in ADMIN_IDS and chat.type != "private":
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} የአድሚን ትዕዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል፤ ለ17 ደቂቃም ታግደሃል።")
        return

    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, data={'subject': subject, 'starter': user.first_name}, name=str(chat.id))
    await update.message.reply_text(f"🚀 የ{subject if subject else 'Random'} ውድድር ተጀመረ!")
    
    # ለማንኛውም አድሚን ማሳወቂያ መላክ
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name}\nቦታ: {chat.title if chat.title else 'Private'}")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve":
            uid = int(context.args[0])
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "✅ ምዝገባዎ ጸድቋል!")
        elif cmd == "stop2":
            jobs = context.job_queue.get_jobs_by_name(str(update.effective_chat.id))
            for j in jobs: j.schedule_removal()
            async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 10") as c:
                rows = await c.fetchall()
                res = "📊 የውድድሩ ውጤት:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
                await update.message.reply_text(res if rows else "ውጤት የለም")
        elif cmd == "keep2":
            jobs = context.job_queue.jobs()
            res = "🟢 ንቁ ውድድሮች:\n\n"
            for j in jobs: res += f"📍 ግሩፕ ID: `{j.name}`\n👤 ያስጀመረው: {j.data.get('starter')}\n\n"
            await update.message.reply_text(res if jobs else "ምንም ንቁ ውድድር የለም።")
        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 20") as c:
                rows = await c.fetchall()
                res = "📜 የቅርብ ጊዜ እንቅስቃሴዎች:\n" + "\n".join([f"{r[2]} | {r[0]} {r[1]}" for r in rows])
                await update.message.reply_text(res if rows else "Log ባዶ ነው")

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "unblock", "oppt", "opptt", "keep2", "log", "stop2"], admin_cmd))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
