import os, json, asyncio, random, aiosqlite, re
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

# --- Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 

# --- Database Initialization ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, chat_name TEXT, timestamp TEXT)''')
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
    
    # Check if muted
    if user and user[5]:
        if datetime.now() < datetime.fromisoformat(user[5]): return

    if not user or user[3] != 'approved' or user[4] == 1: return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_data = await c.fetchone()
        if not poll_data: return
        
        is_correct = (ans.option_ids[0] == poll_data[0])
        
        # Point Logic
        if is_correct:
            if poll_data[1] == 0: # First winner
                points_to_add = 8
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
            else:
                points_to_add = 4
            mark = "✅"
        else:
            points_to_add = 1.5
            mark = "❌"

        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?, ?)", (ans.user.id, ans.user.first_name, mark, "Poll", datetime.now().strftime("%H:%M:%S")))
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points_to_add, ans.user.id))
        await db.commit()

# --- Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"🚫 ቦቱ ለታወቀ ጊዜ ታግዷል። {ADMIN_USERNAME}")
        return

    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው...")
        
        # አድሚን ላይ የሚመጣው የምዝገባ መልዕክት
        admin_msg = (
            f"👤 አዲስ ተመዝጋቢ:\n"
            f"ስም: {user.first_name}\n"
            f"ID: {user.id}\n"
            f"ለማጽደቅ: `/approve {user.id}`\n\n"
            f"ለመከልከል: `/anapprove {user.id}`"
        )
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, admin_msg, parse_mode='Markdown')
        return

    # Admin protection logic
    if user.id not in ADMIN_IDS and chat.type != "private":
        mute_until = (datetime.now() + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_until, user.id))
            await db.commit()
        await update.message.reply_text(f"ውድ {user.first_name} የህግ ጥሰት ስለፈጸሙ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ {user.first_name} አድሚኑ busy ስለሆነ በትዕግስት ይጠብቁ። {ADMIN_USERNAME}")
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subject = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}.get(cmd)
    
    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, data={'subject': subject}, name=str(chat.id))
    await update.message.reply_text(f"🚀 የጥያቄ ውድድር ተጀምሯል!")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve":
            uid = int(context.args[0])
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "ውድ ተማሪ ምዝገባዎ ተቀባይነት አግኝቷል!")
            await update.message.reply_text("ጸድቋል ✅")

        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 15") as c:
                rows = await c.fetchall()
                res = "📜 እንቅስቃሴዎች (Log):\n" + "\n".join([f"{r[0]} {r[1]} @ {r[2]}" for r in rows])
                await update.message.reply_text(res if rows else "Log ባዶ ነው")

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username, points FROM users") as c:
                rows = await c.fetchall()
                res = "📌 የተመዝጋቢዎች ዝርዝር:\n"
                for r in rows:
                    res += f"🔹 ስም: {r[1]}\nID: `{r[0]}`\nነጥብ: {r[2]}\n---\n"
                await update.message.reply_text(res, parse_mode='Markdown')

        elif cmd == "unmute":
            uid = update.message.reply_to_message.from_user.id if update.message.reply_to_message else int(context.args[0])
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "🔊 ማስጠንቀቂያ፦ እገዳዎ ተነስቷል። እባክዎ ደንብ ያክብሩ!")
            await update.message.reply_text(f"ለ {uid} እገዳ ተነስቷል")

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "log", "pin", "unmute"], admin_cmd))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
