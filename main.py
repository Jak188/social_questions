import os, json, asyncio, random, aiosqlite, re
from datetime import datetime, timezone
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
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, chat_name TEXT, timestamp TEXT)''')
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
                await db.execute("INSERT INTO active_polls VALUES (?, ?, ?)", (msg.poll.id, int(q['c']), job.chat_id))
                await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user = await get_user(ans.user.id)
    if not user or user[3] != 'approved' or user[4] == 1: return
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_data = await c.fetchone()
        if not poll_data: return
        is_correct = ans.option_ids[0] == poll_data[0]
        mark = "✅" if is_correct else "❌"
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?, ?)", (ans.user.id, ans.user.first_name, mark, "Active Chat", datetime.now().strftime("%H:%M:%S")))
        if is_correct: await db.execute("UPDATE users SET points = points + 1 WHERE user_id = ?", (ans.user.id,))
        await db.commit()

# --- Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u_data = await get_user(user.id)
    chat = update.effective_chat

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"🚫 ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው አድሚኑ እስኪቀበልዎ ድረስ እባክዎ በትዕግስት ይጠብቁ።")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: {user.id}\nለማጽደቅ: `/approve {user.id}`\nለመከልከል: `/anapprove {user.id}`", parse_mode='Markdown')
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ busy ስለሆነ እባክዎ እስኪቀበልዎ ድረስ በትዕግስት ይጠብቁ። ተቀባይነት ሲያገኙ እናሳውቅዎታለን።\nለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ እናመሰግናለን።")
        return

    if user.id not in ADMIN_IDS and chat.type != "private":
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17 WHERE user_id = ?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"ውድ {user.first_name} የህግ ጥሰት ስለፈጸሙ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subs = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}
    subject = subs.get(cmd) if cmd != "start2" else None

    # ውድድር ሲጀመር ማሳወቂያ
    loc_name = chat.title if chat.title else "Private Chat"
    await update.message.reply_text(f"🚀 የጥያቄ ውድድር በ {loc_name} ተጀምሯል!")

    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, data={'subject': subject}, name=str(chat.id))

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    text = update.message.text.split()
    cmd = text[0][1:].lower()

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve":
            uid = int(context.args[0])
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, f"ውድ ተማሪ ምዝገባዎ ተቀባይነት አግኝቷል!")
            await update.message.reply_text(f"✅ ተጠቃሚ {uid} ጸድቋል።")

        elif cmd == "anapprove":
            uid = int(context.args[0])
            await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
            await db.commit()
            await context.bot.send_message(uid, "❌ ጥያቄዎ ተቀባይነት አላገኘም። እባክዎ እንደገና ይሞክሩ።")
            await update.message.reply_text(f"❌ ተጠቃሚ {uid} ውድቅ ተደርጓል።")

        elif cmd == "rank2":
            async with db.execute("SELECT username, points FROM users WHERE status='approved' ORDER BY points DESC LIMIT 15") as c:
                rows = await c.fetchall()
                res = "📊 የደረጃ ሰንጠረዥ:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
                await update.message.reply_text(res if rows else "ምንም ነጥብ የለም።")

        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 20") as c:
                rows = await c.fetchall()
                res = "📜 የውጤት ዝርዝር (Log):\n" + "\n".join([f"{r[0]} {r[1]} ({r[2]})" for r in rows])
                await update.message.reply_text(res if rows else "Log ባዶ ነው።")

        elif cmd == "clear_log":
            await db.execute("DELETE FROM logs")
            await db.commit()
            await update.message.reply_text("🧹 Log ተሰርዟል።")

        elif cmd == "hmute":
            async with db.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1") as c:
                count = await c.fetchone()
                await update.message.reply_text(f"🔇 በአሁን ሰአት የታገዱ ተጠቃሚዎች ብዛት: {count[0]}")

        elif cmd == "oppt" or cmd == "opptt":
            global GLOBAL_STOP
            is_stopping = (cmd == "oppt")
            GLOBAL_STOP = is_stopping
            notif = f"🚫 ቦቱ ከአድሚን በመጣ ትዕዛዝ ታግዷል።\nለበለጠ መረጃ: {ADMIN_USERNAME}" if is_stopping else f"✅ ቦቱ ወደ ስራ ተመልሷል!\nለበለጠ መረጃ: {ADMIN_USERNAME}"
            
            async with db.execute("SELECT user_id FROM users") as cursor:
                all_users = await cursor.fetchall()
            for row in all_users:
                try: await context.bot.send_message(chat_id=row[0], text=notif)
                except: continue
            await update.message.reply_text("📢 ማሳወቂያው ለሁሉም ተልኳል።")

        elif cmd == "keep2":
            jobs = context.job_queue.jobs()
            res = "🟢 ንቁ ስራዎች:\n" + "\n".join([f"📍 ID: {j.name}" for j in jobs])
            await update.message.reply_text(res if jobs else "ምንም የሚሰራ ውድድር የለም።")

        elif cmd == "close":
            if not update.message.reply_to_message:
                await update.message.reply_text("⚠️ እባክዎ የ /keep2 ዝርዝርን Replay ያድርጉ።")
                return
            match = re.search(r"ID: (-?\d+)", update.message.reply_to_message.text)
            if match:
                target_id = match.group(1)
                for j in context.job_queue.get_jobs_by_name(target_id): j.schedule_removal()
                try: await context.bot.send_message(target_id, f"🏁 ውድድሩ ከአድሚን በመጣ ትዕዛዝ መሰረት ቆሟል።\nለበለጠ መረጃ: {ADMIN_USERNAME}")
                except: pass
                await update.message.reply_text(f"✅ ውድድር {target_id} ቆሟል።")

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "rank2", "log", "clear_log", "hmute", "oppt", "opptt", "keep2", "close"], admin_cmd))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
