import os, json, asyncio, random, aiosqlite, re
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- Configuration ---
TOKEN = "YOUR_BOT_TOKEN_HERE" 
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False 

# --- Database Initialization ---
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

# --- Utility Functions ---
async def get_all_chats():
    chats = set()
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT user_id FROM users") as c:
            for r in await c.fetchall(): chats.add(r[0])
        async with db.execute("SELECT chat_id FROM active_paths") as c:
            for r in await c.fetchall(): chats.add(r[0])
    return chats

async def broadcast_message(context, text):
    chat_ids = await get_all_chats()
    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=text)
            await asyncio.sleep(0.05)
        except: continue

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
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (ans.user.id,)) as c: user = await c.fetchone()
        if not user or user[3] != 'approved' or user[4] == 1: return
        if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return
        
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        points = 8 if (is_correct and p_data[1] == 0) else (4 if is_correct else 1.5)
        
        if is_correct and p_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES (?, ?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# --- Core Logic ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    cmd = update.message.text.split('@')[0].lower() if update.message.text else ""

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ከአድሚን በሰጠው ትእዛዝ መሰረት ቦቱ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
        return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)) as c: u_data = await c.fetchone()

        if not u_data:
            reg_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, reg_time))
            await db.commit()
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው...")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: {user.id}")
            return

        if u_data[3] == 'pending':
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን።")
            return

        if u_data[4] == 1:
            await update.message.reply_text(f"ታግደዋል! ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
            return

        if user.id not in ADMIN_IDS:
            allowed = ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/stop2", "/keep"]
            if chat.type == "private" and cmd not in allowed:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
                await update.message.reply_text("የህግ ጥሰት በመፈፀምዎ ታግደዋል።")
                return

        if cmd in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
            sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
            n = datetime.now()
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, n.strftime("%Y-%m-%d %H:%M")))
            await db.commit()
            jobs = context.job_queue.get_jobs_by_name(str(chat.id))
            for j in jobs: j.schedule_removal()
            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))
            await update.message.reply_text("ውድድር ተጀምሯል! መልካም እድል ለሁላችሁም።")

# --- Admin Controls (With New Commands) ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    
    target_id = None
    if update.message.reply_to_message:
        match = re.search(r"ID: (\d+)", update.message.reply_to_message.text)
        if match: target_id = int(match.group(1))
        else: target_id = update.message.reply_to_message.from_user.id
    elif len(txt) > 1:
        try: target_id = int(txt[1])
        except: pass

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
            await update.message.reply_text(f"ተጠቃሚ {target_id} ጸድቋል።")

        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 20") as c:
                rows = await c.fetchall()
                res = "📜 የተሳታፊዎች እንቅስቃሴ (Log):\n\n"
                for r in rows: res += f"[{r[2]}] {r[0]}: {r[1]}\n"
                await update.message.reply_text(res if len(rows) > 0 else "ምንም ሎግ የለም።")

        elif cmd == "clear_log":
            await db.execute("DELETE FROM logs")
            await db.commit()
            await update.message.reply_text("✅ የቦቱ እንቅስቃሴ መዝገብ (Log) ጸድቷል።")

        elif cmd == "pin":
            async with db.execute("SELECT COUNT(*) FROM users") as c1: users_count = (await c1.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM active_paths") as c2: groups_count = (await c2.fetchone())[0]
            res = f"📍 የቦቱ መረጃ (Status):\n\n👥 ጠቅላላ ተመዝጋቢዎች: {users_count}\n🏢 ጠቅላላ ግሩፖች: {groups_count}"
            await update.message.reply_text(res)

        elif cmd == "gof":
            async with db.execute("SELECT username, reg_at FROM users WHERE status = 'pending'") as c:
                rows = await c.fetchall()
                res = "⏳ የምዝገባ ጥያቄ ላይ ያሉ:\n\n"
                for r in rows: res += f"👤 {r[0]} - የጠየቀበት: {r[1]}\n"
                await update.message.reply_text(res if len(rows) > 0 else "ምንም በመጠባበቅ ላይ ያለ የለም።")

        elif cmd == "rank2":
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                res = "📊 የደረጃ ሰንጠረዥ (Top 15):\n\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} ነጥብ\n"
                await update.message.reply_text(res)

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points = 0")
            await db.commit()
            await update.message.reply_text("🔄 ሁሉም ነጥቦች ወደ 0 ተመልሰዋል (Rank Cleared)።")

        elif cmd == "hmute":
            async with db.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1") as c1: blocked = (await c1.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM users WHERE muted_until IS NOT NULL") as c2: muted = (await c2.fetchone())[0]
            res = f"🔇 የቅጣት መረጃ:\n\n🚫 የታገዱ (Block): {blocked}\n🤐 የታገዱ (Mute): {muted}"
            await update.message.reply_text(res)

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await broadcast_message(context, "ከአድሚን በመጣ ትእዛዝ መሰረት ቦቱ ቆሟል።")
            await update.message.reply_text("ቦቱ ቆሟል።")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await broadcast_message(context, "ቦቱ አሁን ወደ ስራ ተመልሷል።")
            await update.message.reply_text("ቦቱ ተከፍቷል።")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            await update.message.reply_text("🏁 ውድድሩ በዚህ ግሩፕ ተጠናቋል።")

# --- Startup ---
async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    status = "✅ ቦቱ አብርቷል" if m.new_chat_member.status == 'member' else "❌ ቦቱ አጥፍቷል"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, f"{status}\nበ፡ {update.effective_user.first_name}")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "log", "clear_log", "pin", "gof", "rank2", "clear_rank2", "hmute", "oppt", "opptt", "stop2"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
