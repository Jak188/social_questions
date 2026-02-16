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

# --- 2. Config ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False
bot_active_sessions = {}

# --- 3. Database ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', muted_until TEXT, is_blocked INTEGER DEFAULT 0, reg_date TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_done INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, username TEXT, action TEXT, timestamp TEXT)''')
        await db.commit()

# --- 4. Helpers ---
def load_questions(subject=None):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            if subject: return [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
            return all_q
    except: return []

async def get_user(user_id):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

# --- 5. Core Logic ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    questions = load_questions(job.data.get('subject'))
    if not questions: return
    q = random.choice(questions)
    try:
        msg = await context.bot.send_poll(
            job.chat_id, f"[{q.get('subject', 'Random')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', '')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (msg.poll.id, int(q['c']), job.chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user = await get_user(ans.user.id)
    if not user or user[6] == 1 or user[4] != 'approved': return
    if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as cursor:
            poll_data = await cursor.fetchone()
    
    if not poll_data: return
    is_correct = ans.option_ids[0] == poll_data[1]
    points = 1.5 # Default for participation
    
    if is_correct:
        if poll_data[3] == 0:
            points = 8
            await db.execute("UPDATE active_polls SET first_done = 1 WHERE poll_id = ?", (ans.poll_id,))
            await context.bot.send_message(poll_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
        else:
            points = 4
    
    action = "✔️" if is_correct else "❎"
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?)", (ans.user.id, ans.user.first_name, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()

# --- 6. Commands ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    db_user = await get_user(user.id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not db_user:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, full_name, status, reg_date) VALUES (?, ?, ?, 'pending', ?)", 
                             (user.id, user.username, user.first_name, now))
            await db.commit()
        msg = f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ እባክዎ በትዕግስት ይጠብቁ።"
        await update.message.reply_text(msg)
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"📩 አዲስ የምዝገባ ጥያቄ:\nስም: {user.first_name}\nID: `{user.id}`\nለማጽደቅ /approve ይበሉ")
        return

    if db_user[4] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው ቢዚ ነው። ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን።")
        return

    if db_user[6] == 1:
        await update.message.reply_text(f"ከአድሚን በመጣ ትዕዛዝ መሰረት ለጊዜው ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ።")
        return

    # Guard for Group
    if chat.type != "private" and user.id not in ADMIN_IDS:
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} ያለፈቃድ ትዕዛዝ በመንካትዎ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    # Start Quiz
    cmd = update.message.text.split('@')[0][1:].lower()
    subj = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}.get(cmd)
    
    jobs = context.job_queue.get_jobs_by_name(str(chat.id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, interval=180, first=5, chat_id=chat.id, data={'subject': subj}, name=str(chat.id))
    
    bot_active_sessions[chat.id] = {"name": chat.title or user.first_name, "start": now, "type": chat.type}
    await update.message.reply_text(f"🚀 የ{subj or 'Random'} ውድድር ተጀምሯል!")
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"📢 ቦቱ ተነስቷል!\nማን: {user.first_name} ({user.id})\nየት: {chat.title or 'Private'}\nሰዓት: {now}")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if not jobs: return
    for j in jobs: j.schedule_removal()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        if update.effective_chat.type == "private":
            u = await get_user(update.effective_user.id)
            await update.message.reply_text(f"🏁 ቦቱ ቆሟል። የእርስዎ ነጥብ: {u[3]}")
        else:
            async with db.execute("SELECT full_name, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as c:
                rows = await c.fetchall()
            res = "📊 Best 15:\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]}" for i, r in enumerate(rows)])
            await update.message.reply_text(res)
    
    if chat_id in bot_active_sessions: del bot_active_sessions[chat_id]
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"🏁 ቦቱ ጠፍቷል በ: {update.effective_user.first_name} ({chat_id})")

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    cmd = update.message.text.split()[0][1:].lower()
    global GLOBAL_STOP

    try:
        # Oppt (Global Stop)
        if cmd == "oppt":
            GLOBAL_STOP = True
            msg = f"🛑 ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ።"
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT user_id FROM users") as c:
                    for r in await c.fetchall():
                        try: await context.bot.send_message(r[0], msg)
                        except: continue
            await update.message.reply_text("🛑 ቦቱ ለሁሉም ቆሟል።")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await update.message.reply_text("✅ ቦቱ ተመልሷል።")

        # Keep / Keep2
        elif cmd in ["keep", "keep2"]:
            res = "🟢 Active Sessions:\n"
            for cid, data in bot_active_sessions.items():
                res += f"- {data['name']} (`{cid}`) ጀመረ: {data['start']}\n"
            await update.message.reply_text(res or "ምንም የለም")

        # Pin (User Info)
        elif cmd == "pin":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT full_name, user_id, username FROM users") as c:
                    rows = await c.fetchall()
            res = f"👥 ተመዝጋቢዎች ({len(rows)}):\n" + "\n".join([f"- {r[0]} (`{r[1]}`) @{r[2]}" for r in rows])
            await update.message.reply_text(res)

        # Log
        elif cmd == "log":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 30") as c:
                    rows = await c.fetchall()
            res = "📜 ዝርዝር ሎግ:\n" + "\n".join([f"{r[3]} | {r[1]} {r[2]}" for r in rows])
            await update.message.reply_text(res)

        # Hmute (Muted/Blocked list)
        elif cmd == "hmute":
            async with aiosqlite.connect('quiz_bot.db') as db:
                async with db.execute("SELECT full_name, user_id, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                    rows = await c.fetchall()
            res = "🚫 የታገዱ/Mute የሆኑ:\n"
            for r in rows:
                status = "Blocked" if r[2]==1 else "Muted"
                res += f"- {r[0]} (`{r[1]}`) [{status}]\n"
            await update.message.reply_text(res or "ምንም የለም")

        # Reply based actions (Close, Block, Approve, etc)
        if update.message.reply_to_message:
            target_text = update.message.reply_to_message.text
            import re
            t_id = re.search(r'ID: `(\d+)`|`(\d+)`|(\d+)', target_text)
            uid = int(t_id.group(1) or t_id.group(2) or t_id.group(3)) if t_id else None
            
            if not uid: return

            async with aiosqlite.connect('quiz_bot.db') as db:
                if cmd == "approve":
                    await db.execute("UPDATE users SET status='approved' WHERE user_id=?", (uid,))
                    await context.bot.send_message(uid, "🎉 እንኳን ደስ አለዎት! ምዝገባዎ ጸድቋል።")
                elif cmd == "anapprove":
                    await context.bot.send_message(uid, "❌ ጥያቄዎ ተቀባይነት አላገኘም። እባክዎ እንደገና ይሞክሩ።")
                elif cmd == "block":
                    await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (uid,))
                    await context.bot.send_message(uid, f"🚫 ታግደዋል። {ADMIN_USERNAME} ን ያነጋግሩ።")
                elif cmd == "unblock":
                    await db.execute("UPDATE users SET is_blocked=0, muted_until=NULL WHERE user_id=?", (uid,))
                    await context.bot.send_message(uid, "✅ እገዳዎ ተነስቷል!")
                elif cmd == "unmute" or cmd == "unmute2":
                    await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?", (uid,))
                    u = await get_user(uid)
                    await context.bot.send_message(uid, f"ተማሪ {u[2]} እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ።")
                elif cmd == "close":
                    jobs = context.job_queue.get_jobs_by_name(str(uid))
                    for j in jobs: j.schedule_removal()
                await db.commit()
            await update.message.reply_text(f"Done: {cmd} on {uid}")

    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def guard_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS: return
    if update.effective_chat.type == "private":
        # Block if non-allowed command
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"🚫 የህግ ጥሰት! ያለፈቃድ ትዕዛዝ ስለተጠቀሙ ታግደዋል። {ADMIN_USERNAME} ን ያነጋግሩ።")

# --- 7. Main ---
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # User Commands
    user_cmds = ["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"]
    app_bot.add_handler(CommandHandler(user_cmds, start_handler))
    app_bot.add_handler(CommandHandler(["stop2", "rank2"], stop_cmd))
    
    # Admin Commands
    adm_cmds = ["oppt", "opptt", "keep", "keep2", "pin", "log", "hmute", "approve", "anapprove", "block", "unblock", "unmute", "unmute2", "close", "clear_rank2", "clear_log", "gof", "info"]
    app_bot.add_handler(CommandHandler(adm_cmds, admin_actions))
    
    # Poll & Guard
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(MessageHandler(filters.COMMAND & filters.ChatType.PRIVATE, guard_logic))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
