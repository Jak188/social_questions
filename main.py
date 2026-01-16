import os, json, asyncio, random, aiosqlite, re
from datetime import datetime
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
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER)''')
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
                await db.execute("INSERT INTO active_polls VALUES (?, ?, ?)", (msg.poll.id, int(q['c']), job.chat_id))
                await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user = await get_user(ans.user.id)
    if not user or user[3] != 'approved' or user[4] == 1: return
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_data = await c.fetchone()
        if not poll_data: return
        is_correct = (ans.option_ids[0] == poll_data[0])
        mark = "✅" if is_correct else "❌"
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?, ?)", (ans.user.id, ans.user.first_name, mark, "Active", datetime.now().strftime("%H:%M:%S")))
        if is_correct: await db.execute("UPDATE users SET points = points + 1 WHERE user_id = ?", (ans.user.id,))
        await db.commit()

# --- Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"🚫 ቦቱ ከአድሚን በመጣ ትዕዛዝ ታግዷል። {ADMIN_USERNAME}")
        return

    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው...")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ተመዝጋቢ: {user.first_name} (ID: {user.id})")
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ {user.first_name} አድሚኑ busy ስለሆነ በትዕግስት ይጠብቁ። {ADMIN_USERNAME}")
        return

    # ውድድር ሲጀመር
    cmd = update.message.text.split('@')[0][1:].lower()
    subject = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}.get(cmd)
    
    start_time = datetime.now().strftime("%H:%M:%S")
    loc = chat.title if chat.title else "Private"
    
    # ለአድሚን ብቻ የሚላክ ማሳወቂያ
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"🔔 ውድድር ተጀመረ!\n📍 ቦታ: {loc}\n⏰ ሰዓት: {start_time}\n👤 በ: {user.first_name}\nID: {chat.id}")

    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, data={'subject': subject, 'starter': user.first_name, 'time': start_time}, name=str(chat.id))
    await update.message.reply_text(f"🚀 የጥያቄ ውድድር በ {loc} ተጀምሯል!")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve":
            uid = int(context.args[0])
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "ውድ ተማሪ ምዝገባዎ ተቀባይነት አግኝቷል!")

        elif cmd == "rank2":
            if update.effective_chat.type == "private":
                u = await get_user(update.effective_user.id)
                await update.message.reply_text(f"📊 የእርስዎ ነጥብ: {u[2]}")
            else:
                async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as c:
                    rows = await c.fetchall()
                    res = "📊 የደረጃ ሰንጠረዥ (0 ያልሆኑ):\n" + "\n".join([f"{r[0]}: {r[1]}" for r in rows])
                    await update.message.reply_text(res if rows else "ምንም ነጥብ የለም")

        elif cmd in ["oppt", "opptt"]:
            global GLOBAL_STOP
            GLOBAL_STOP = (cmd == "oppt")
            msg = "🚫 ቦቱ ታግዷል" if GLOBAL_STOP else "✅ ቦቱ ተከፍቷል"
            async with db.execute("SELECT user_id FROM users") as cur:
                all_u = await cur.fetchall()
                for r in all_u:
                    try: await context.bot.send_message(r[0], f"{msg}። {ADMIN_USERNAME}")
                    except: continue
            await update.message.reply_text(f"ማሳወቂያ ተልኳል: {msg}")

        elif cmd == "keep2":
            jobs = context.job_queue.jobs()
            res = "🟢 ንቁ ውድድሮች:\n"
            for j in jobs:
                res += f"📍 ID: {j.name} | Starter: {j.data.get('starter')} | Time: {j.data.get('time')}\n---\n"
            await update.message.reply_text(res if jobs else "ንቁ ውድድር የለም")

        elif cmd == "close" or cmd == "block":
            target_id = None
            if update.message.reply_to_message:
                m = re.search(r"ID: (-?\d+)", update.message.reply_to_message.text)
                if m: target_id = m.group(1)
            elif context.args: target_id = context.args[0]

            if target_id:
                if cmd == "close":
                    for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
                    try: await context.bot.send_message(target_id, f"🏁 ውድድሩ ቆሟል። {ADMIN_USERNAME}")
                    except: pass
                else:
                    await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target_id,))
                    await db.commit()
                await update.message.reply_text(f"ተፈጽሟል: {cmd} {target_id}")

        elif cmd == "pin":
            async with db.execute("SELECT COUNT(*) FROM users") as c:
                count = await c.fetchone()
                await update.message.reply_text(f"👥 ጠቅላላ ተመዝጋቢ: {count[0]}")

        elif cmd == "mute":
            uid = update.message.reply_to_message.from_user.id if update.message.reply_to_message else context.args[0]
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (uid,))
            await db.commit()
            await update.message.reply_text(f"🔇 ተጠቃሚ {uid} ታግዷል")

        elif cmd == "unmute":
            uid = update.message.reply_to_message.from_user.id if update.message.reply_to_message else context.args[0]
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (uid,))
            await db.commit()
            await update.message.reply_text(f"🔊 እገዳ ተነስቷል ለ {uid}")

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "rank2", "oppt", "opptt", "keep2", "close", "block", "pin", "mute", "unmute"], admin_cmd))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
