PK:
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
    user = await get_user(ans.user.id)
    if not user or user[3] != 'approved' or user[4] == 1: return
    if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        # 7. ነጥብ አሰጣጥ (8, 4, 1.5)
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
    u_data = await get_user(user.id)
    cmd = update.message.text.split('@')[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
        return

    if not u_data:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, now))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው ጥያቄውን አድሚኑ እስኪቀበልዎ እባክዎ በትእግስት ይጠብቁ")
        for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: {user.id}\nUsername: @{user.username}")
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ፈቃድ እስከሚሰጥዎ ድረስ እባክዎ በትዕግስት ይጠብቁ\nለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if u_data[4] == 1:
        await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለተ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
        return

    # 4. የቅጣት ስርዓት (Private vs Group)
    if chat.type == "private":
        allowed_p = ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/keep"]
        if cmd not in allowed_p and user.id not in ADMIN_IDS:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"የህግ ጥሰት: ከተፈቀደልዎ ትእዛዝ ውጭ አዘዋል\nከ {ADMIN_USERNAME}")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🚫 ተማሪ በግል ታግዷል:\nስም: {user.first_name}\nID: {user.id}\nምክንያት: ያልተፈቀደ ትእዛዝ ({cmd})")
            return
    else:
        if cmd not in ["/start2", "/stop2"] and user.id not in ADMIN_IDS:
            mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
                await db.commit()
            await update.message.reply_text(f"የህግ ጥሰት.. {user.first_name} የአድሚን ትእዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል ለ17 ደቂቃ ታግደሃል")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"⚠️ ተማሪ {user.first_name} (ID: {user.id}) ከግሩፕ {chat.title} ታግዷል። እገዳውን ለማንሳት replay አድርገህ /unmute2 በል")
            return

    # 10. ውድድር መጀመር
    if cmd in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
        sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
        n = datetime.now()
        
        # 6. ለኔ ያሳውቅ
        inf = f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name} (ID: {user.id})\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {n.strftime('%H:%M:%S')} | ቀን: {n.strftime('%Y-%m-%d')}"
        for adm in ADMIN_IDS: await context.bot.send_message(adm, inf)

        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, n.strftime("%Y-%m-%d %H:%M")))
            await db.commit()

jobs = context.job_queue.get_jobs_by_name(str(chat.id))
        for j in jobs: j.schedule_removal()
        # 9. በየ 3 ደቂቃ (180 ሰከንድ)
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub, 'starter': user.first_name}, name=str(chat.id))
        await update.message.reply_text("ዉድ ተማሪዎች ውድድር መጀመሩን እየገፅን ቀድሞ ለመለሰ 8ነጥብ ሌላ ላገኘ 4ነጥብ ለተሳተፉ 1.5ነጥብ ያገኛሉ")

# --- Admin Functions ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        target = None
        if update.message.reply_to_message:
            target = update.message.reply_to_message.from_user.id
        elif len(txt) > 1:
            try: target = int(txt[1])
            except: pass

        if cmd == "approve" and target:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target,))
            await db.commit()
            u = await get_user(target)
            await context.bot.send_message(target, f"ውድ ተማሪ {u[1]} ጥያቄዎ ተቀባይነት አግኝቷል ለመጀመር መግለጫው ላይ ያሉትን ትእዛዞች ይዘዙ")
            await update.message.reply_text(f"ተጠቃሚ {target} ጸድቋል")
        
        elif cmd == "anapprove" and target:
            u = await get_user(target)
            await db.execute("DELETE FROM users WHERE user_id = ?", (target,))
            await db.commit()
            await context.bot.send_message(target, f"ውድ ተማሪ {u[1] if u else ''} ይቅርታ ጥያቄዎ ተቀባይነት አላገኘም እባክዎ ደግመው ይሞክሩ ከ {ADMIN_USERNAME}")

        elif cmd == "unmute2" and update.message.reply_to_message:
            uid = update.message.reply_to_message.from_user.id
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (uid,))
            await db.commit()
            u = await get_user(uid)
            await update.message.reply_to_message.reply_text(f"ተማሪ {u[1] if u else ''} እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ")

        elif cmd == "unblock" and target:
            await db.execute("UPDATE users SET is_blocked = 0, status='approved' WHERE user_id = ?", (target,))
            await db.commit()
            await context.bot.send_message(target, "እገዳዎ ተነስቷል")
            await update.message.reply_text("እገዳው ተነስቷል")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            await update.message.reply_text("ውድድሩ በድል ተጠናቋል!")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🏁 ውድድር በ {update.effective_user.first_name} ቆሟል (ሰዓት: {datetime.now().strftime('%H:%M:%S')})")

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await update.message.reply_text(f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
        elif cmd == "opptt":
            GLOBAL_STOP = False
            for adm in ADMIN_IDS: await context.bot.send_message(adm, "ቦቱ ወደ ስራ ተመልሷል @penguiner")
            await update.message.reply_text("ቦቱ ተከፍቷል")

        elif cmd == "log": # 1. Log with ✓ and X
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY date DESC, timestamp DESC LIMIT 30") as c:
                res = "📜 ዝርዝር መዝገብ:\n" + "\n".join([f"{r[2]} {r[3]} | {r[0]} {r[1]}" for r in await c.fetchall()])
                await update.message.reply_text(res)

        elif cmd == "hmute": # 2. Hmute
            async with db.execute("SELECT user_id, username, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 የታገዱ (Users/Groups):\n"
                for r in await c.fetchall():
                    status = "blocked" if r[2] == 1 else "muted"
                    res += f"ID: {r[0]} | @{r[1]} | {status}\n"
                await update.message.reply_text(res if len(res)>25 else "ምንም የታገደ የለም")

elif cmd == "info": # 3. Info with Registration Date
            async with db.execute("SELECT user_id, username, reg_at FROM users") as c:
                res = "ℹ️ የተመዘገቡ ተማሪዎች:\n"
                for r in await c.fetchall(): res += f"ID: {r[0]} | @{r[1]} | መቼ: {r[2]}\n"
                await update.message.reply_text(res)

        elif cmd == "keep2": # 5. Keep2
            async with db.execute("SELECT * FROM active_paths") as c:
                res = "🔍 ንቁ ውድድሮች:\n"
                for p in await c.fetchall(): res += f"ቦታ: {p[1]} (ID: {p[0]}) | በ: {p[2]} | የጀመረው: {p[3]}\n"
                await update.message.reply_text(res if len(res)>20 else "ምንም ንቁ ውድድር የለም")

async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    txt = f"{'✅ ቦቱ አብርቷል' if m.new_chat_member.status == 'member' else '❌ ቦቱ አጥፍቷል'}...\nበ: {u.first_name} (ID: {u.id})"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, txt)

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "close", "unblock", "unmute2", "unmute", "stop2", "oppt", "opptt", "log", "hmute", "info", "keep2", "rank2", "clear_rank2"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if name == 'main':
    main()
