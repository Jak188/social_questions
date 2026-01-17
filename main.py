import os, json, asyncio, random, aiosqlite, re
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server (Uptime) ---
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

# --- Database ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0, muted_until TEXT, reg_at TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_paths 
            (chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, starter_user TEXT, start_time TEXT, count INTEGER DEFAULT 0)''')
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
                await db.execute("UPDATE active_paths SET count = count + 1 WHERE chat_id = ?", (job.chat_id,))
                await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    if GLOBAL_STOP: return
    user = await get_user(ans.user.id)
    
    # 7. ነጥብ አሰጣጥ (8, 4, 1.5)
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        points = 8 if (is_correct and p_data[1] == 0) else (4 if is_correct else 1.5)
        
        if is_correct and p_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
        
        if user and user[3] == 'approved' and user[4] == 0:
            await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        
        # 1. /log (የሁሉም ሰው እንቅስቃሴ)
        now = datetime.now()
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES (?, ?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✓" if is_correct else "X", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# --- Core Logic & Rules ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)
    cmd = update.message.text.split('@')[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
        return

    # ምዝገባ
    if not u_data:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.username, now))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው...")
        for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ጥያቄ: {user.first_name} (ID: {user.id})")
        return

    # 4. የቅጣት ስርዓት (Private Security)
    if chat.type == "private" and cmd not in ["/start2", "/stop2", "/rank2", "/keep2"] and user.id not in ADMIN_IDS:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
            await db.commit()
        await update.message.reply_text("የህግ ጥሰት.. በቋሚነት ታግደሃል")
        return

    # 4. የቅጣት ስርዓት (Group Rule)
    if chat.type != "private" and cmd not in ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"] and user.id not in ADMIN_IDS:
        mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
            await db.commit()
        await update.message.reply_text(f"የህግ ጥሰት.. {user.first_name} 3.17 ነጥብ ተቀንሶብሃል ለ17 ደቂቃ ታግደሃል")
        return

    # 10. ውድድር መጀመር & 9. 3 ደቂቃ (180s)
    if cmd in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
        sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
        now = datetime.now()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?, ?, 0)", 
                             (chat.id, chat.title if chat.title else "Private", user.first_name, user.username, now.strftime("%H:%M:%S")))
            await db.commit()
        
        jobs = context.job_queue.get_jobs_by_name(str(chat.id))
        for j in jobs: j.schedule_removal()
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))
        await update.message.reply_text("ዉድ ተማሪዎች ውድድር መጀመሩን እየገፅን...")

# --- Admin Functions ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    global GLOBAL_STOP
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        target = update.message.reply_to_message.from_user.id if update.message.reply_to_message else (int(txt[1]) if len(txt)>1 else None)

        # /oppt & /opptt (Global Stop/Start)
        if cmd == "oppt":
            GLOBAL_STOP = True
            msg = f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}"
            async with db.execute("SELECT user_id FROM users") as c:
                for r in await c.fetchall():
                    try: await context.bot.send_message(r[0], msg)
                    except: pass
            await update.message.reply_text("ቦቱ ለሁሉም ቆሟል ✅")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            async with db.execute("SELECT user_id FROM users") as c:
                for r in await c.fetchall():
                    try: await context.bot.send_message(r[0], "ቦቱ ተከፍቷል ✅")
                    except: pass
            await update.message.reply_text("ቦቱ ተከፍቷል ✅")

        # /gof (Pending Users)
        elif cmd == "gof":
            async with db.execute("SELECT user_id, username FROM users WHERE status = 'pending'") as c:
                pending = await c.fetchall()
                if not pending:
                    await update.message.reply_text("ምንም አዲስ የምዝገባ ጥያቄ የለም")
                    return
                for p in pending:
                    msg = f"🆕 አዲስ ጥያቄ:\n🆔 ID: {p[0]}\n👤 Username: @{p[1]}\n\nለመፍቀድ: `/approve {p[0]}`"
                    await update.message.reply_text(msg)

        # /log (Detailed Activity)
        elif cmd == "log":
            async with db.execute("SELECT user_id, name, action, timestamp, date FROM logs ORDER BY date DESC, timestamp DESC LIMIT 20") as c:
                logs = await c.fetchall()
                if not logs:
                    await update.message.reply_text("ምንም ሎግ የለም")
                    return
                for l in logs:
                    msg = f"👤 ስም: {l[1]}\n🆔 ID: {l[0]}\n📊 ውጤት: {l[2]}\n⏰ ሰዓት: {l[4]} {l[3]}"
                    await update.message.reply_text(msg)

        # /keep2 (Active Quizzes)
        elif cmd == "keep2":
            async with db.execute("SELECT chat_title, starter_name, starter_user, start_time, count FROM active_paths") as c:
                active = await c.fetchall()
                if not active:
                    await update.message.reply_text("ምንም ንቁ ውድድር የለም")
                    return
                for a in active:
                    msg = f"📍 ቦታ: {a[0]}\n👤 የጀመረው: {a[1]} (@{a[2]})\n⏰ ሰዓት: {a[3]}\n📝 ጥያቄዎች: {a[4]}"
                    await update.message.reply_text(msg)

        # /rank2 (Top 15)
        elif cmd == "rank2":
            async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as c:
                rows = await c.fetchall()
                res = "📊 የሁሉንም ተማሪዎች ውጤት (Top 15):\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} pts" for i,r in enumerate(rows)])
                await update.message.reply_text(res if rows else "ምንም ውጤት የለም")

        # /clear_log2, /approve, /unmute2...
        elif cmd == "clear_log2":
            await db.execute("DELETE FROM logs")
            await db.commit()
            await update.message.reply_text("♻️ የሎግ መዝገብ ጸድቷል")

        elif cmd == "approve" and target:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target,))
            await db.commit()
            await update.message.reply_text(f"ተጠቃሚ {target} ጸድቋል ✅")

        elif cmd == "unmute2" and update.message.reply_to_message:
            uid = update.message.reply_to_message.from_user.id
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (uid,))
            await db.commit()
            await update.message.reply_to_message.reply_text("እገዳዎ በአድሚን ተነስቷል ✅")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id = ?", (update.effective_chat.id,))
            await db.commit()
            await update.message.reply_text("ውድድሩ በድል ተጠናቋል!")

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "rank2", "stop2"], start_handler))
    app_bot.add_handler(CommandHandler(["log", "gof", "keep2", "approve", "unmute2", "oppt", "opptt", "clear_log2"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
