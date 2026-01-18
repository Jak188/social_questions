import os, json, asyncio, random, aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server for Render (Uptime) ---
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
            (chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT)''')
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
    u_data = await get_user(ans.user.id)
    if not u_data or u_data[3] != 'approved' or u_data[4] == 1: return
    if u_data[5] and datetime.now(timezone.utc) < datetime.fromisoformat(u_data[5]): return
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        points = 0
        if is_correct:
            if p_data[1] == 0:
                points = 8
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
                await context.bot.send_message(p_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
            else: points = 4
        else: points = 1.5
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES (?, ?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# --- Core Handlers ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)
    text = update.message.text.split('@')[0].lower() if update.message.text else ""

    # 1. Global Stop Check
    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ቦቱ ለጊዜው ቆሟል። @penguiner ን ያናግሩ")
        return

    # 2. Registration Logic
    if text == "/start2" or text.startswith("/"):
        if not u_data:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, now_str))
                await db.commit()
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው፤ አድሚኑ እስኪቀበልዎ በትዕግስት ይጠብቁ።")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ: {user.first_name} (ID: {user.id})")
            return
        elif u_data[3] == 'pending':
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው busy ነው፤ ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን።")
            return

    # 3. Security & Rules
    if user.id not in ADMIN_IDS:
        if chat.type == "private":
            allowed = ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/keep"]
            if text not in allowed:
                async with aiosqlite.connect('quiz_bot.db') as db:
                    await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                    await db.commit()
                await update.message.reply_text(f"የህግ ጥሰት! ያልተፈቀደ ትዕዛዝ በመጠቀሞ ታግደዋል። @penguiner")
                return
        else: # Group Rules
            if text.startswith("/") and text not in ["/start2", "/stop2"]:
                mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
                async with aiosqlite.connect('quiz_bot.db') as db:
                    await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
                    await db.commit()
                await update.message.reply_text(f"የህግ ጥሰት! {user.first_name} 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
                for adm in ADMIN_IDS: await context.bot.send_message(adm, f"⚠️ እገዳ: {user.first_name} በግሩፕ {chat.title} ታግዷል። /unmute2 ይበሉ")
                return

    # 4. Starting Quiz
    if text in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
        sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(text)
        now = datetime.now()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, now.strftime("%Y-%m-%d %H:%M")))
            await db.commit()
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))
        await update.message.reply_text("ውድድሩ ተጀምሯል! መልካም እድል!")
        for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🚀 ውድድር ተጀመረ በ: {user.first_name} ({chat.type})")

# --- Admin Controls ---
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    target = update.message.reply_to_message.from_user.id if update.message.reply_to_message else (int(txt[1]) if len(txt)>1 else None)

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve" and target:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target,))
            await db.commit()
            await context.bot.send_message(target, "ምዝገባዎ ተቀባይነት አግኝቷል!")
        elif cmd == "anapprove" and target:
            await db.execute("DELETE FROM users WHERE user_id = ?", (target,))
            await db.commit()
            await context.bot.send_message(target, "ውድቅ ተደርጓል፤ እባክዎ እንደገና ይሞክሩ።")
        elif cmd == "unmute2" or cmd == "unmute":
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target,))
            await db.commit()
            await update.message.reply_text("እገዳው ተነስቷል።")
        elif cmd == "log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY date DESC LIMIT 20") as c:
                res = "📜 LOG:\n" + "\n".join([f"{r[2]} | {r[0]} {r[1]}" for r in await c.fetchall()])
                await update.message.reply_text(res)
        elif cmd == "hmute":
            async with db.execute("SELECT user_id, username, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 የታገዱ:\n"
                for r in await c.fetchall(): res += f"ID: {r[0]} | @{r[1]} | {'Blocked' if r[2] == 1 else 'Muted'}\n"
                await update.message.reply_text(res)

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    msg = f"{'✅ ቦቱ አብርቷል' if m.new_chat_member.status == 'member' else '❌ ቦቱ አጥፍቷል'} በ: {u.first_name}"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, msg)

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "unmute", "unmute2", "log", "hmute", "oppt", "opptt", "rank2", "info", "keep2"], admin_cmd))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app_bot.add_handler(MessageHandler(filters.COMMAND, handle_message))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
