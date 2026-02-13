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
def keep_alive(): Thread(target=run, daemon=True).start()

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
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (uid,)) as c: 
            return await c.fetchone()

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
            msg = await context.bot.send_poll(job.chat_id, f"📚 [{q.get('subject', 'General')}] {q['q']}", q['o'], 
                is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', ''))
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (?, ?, ?)", (msg.poll.id, int(q['c']), job.chat_id))
                await db.commit()
    except Exception as e:
        print(f"Quiz Error: {e}")

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
        # ነጥብ አሰጣጥ (8, 4, 1.5)
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
    if not update.message: return
    cmd = update.message.text.split('@')[0].split()[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
        return

    if not u_data:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, now))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው አድሚኑ እስኪቀበልዎ በትእግስት ይጠብቁ")
        for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: <code>{user.id}</code>", parse_mode='HTML')
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ፈቃድ እስከሚሰጥዎ በትዕግስት ይጠብቁ\nለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if u_data[4] == 1:
        await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    # የቅጣት ስርዓት (Private vs Group Security)
    if chat.type == "private":
        allowed_p = ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2"]
        if cmd not in allowed_p and user.id not in ADMIN_IDS:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"የህግ ጥሰት: ያልተፈቀደ ትእዛዝ!\nታግደዋል። አድሚን ያነጋግሩ: {ADMIN_USERNAME}")
            return
    else:
        if cmd.startswith('/') and cmd not in ["/start2", "/stop2"] and user.id not in ADMIN_IDS:
            mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
                await db.commit()
            await update.message.reply_text(f"የህግ ጥሰት! {user.first_name} የአድሚን ትእዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል ለ17 ደቂቃ ታግደሃል")
            return

    # ውድድር መጀመር
    if cmd in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
        sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
        n = datetime.now()
        
        # ለኔ ያሳውቅ (Admin Notification)
        inf = f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name}\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {n.strftime('%H:%M:%S')}"
        for adm in ADMIN_IDS: await context.bot.send_message(adm, inf)

        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, n.strftime("%Y-%m-%d %H:%M")))
            await db.commit()

        jobs = context.job_queue.get_jobs_by_name(str(chat.id))
        for j in jobs: j.schedule_removal()
        
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))
        await update.message.reply_text("🚀 ውድድር ተጀምሯል!\nቀድሞ ለመለሰ 8 ነጥብ | በትክክል ለመለሰ 4 ነጥብ | ለተሳተፈ 1.5 ነጥብ")

# --- Admin Functions ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        target = None
        if update.message.reply_to_message:
            # ከ Reply ላይ ID መፈለጊያ (Regex)
            msg_text = update.message.reply_to_message.text
            match = re.search(r'ID:\s*(\d+)', msg_text)
            if match: target = int(match.group(1))
            else: target = update.message.reply_to_message.from_user.id
        elif len(txt) > 1:
            try: target = int(txt[1])
            except: pass

        if cmd == "approve" and target:
            await db.execute("UPDATE users SET status = 'approved', is_blocked = 0 WHERE user_id = ?", (target,))
            await db.commit()
            try: await context.bot.send_message(target, "✅ ጥያቄዎ ተቀባይነት አግኝቷል! አሁን መሳተፍ ይችላሉ።")
            except: pass
            await update.message.reply_text(f"ተጠቃሚ {target} ጸድቋል")
        
        elif cmd == "anapprove" and target:
            await db.execute("DELETE FROM users WHERE user_id = ?", (target,))
            await db.commit()
            try: await context.bot.send_message(target, f"❌ ይቅርታ ጥያቄዎ ተቀባይነት አላገኘም ደግመው ይሞክሩ። {ADMIN_USERNAME}")
            except: pass
            await update.message.reply_text("ተጠቃሚው ተሰርዟል")

        elif cmd == "unmute2" and target:
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target,))
            await db.commit()
            await update.message.reply_text("እገዳው ተነስቷል")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id = ?", (update.effective_chat.id,))
            await db.commit()
            await update.message.reply_text("🏁 ውድድሩ ተጠናቋል!")

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await update.message.reply_text("🚫 ቦቱ ለጊዜው ታግዷል")
            
        elif cmd == "opptt":
            GLOBAL_STOP = False
            await update.message.reply_text("✅ ቦቱ ወደ ስራ ተመልሷል")

        elif cmd == "log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 30") as c:
                res = "📜 የቅርብ ጊዜ መዝገቦች:\n"
                for r in await c.fetchall(): res += f"{r[2]} {r[3]} | {r[0]} {r[1]}\n"
                await update.message.reply_text(res if len(res) > 20 else "መዝገብ ባዶ ነው")

        elif cmd == "info":
            async with db.execute("SELECT user_id, username, reg_at FROM users") as c:
                res = "ℹ️ የተመዘገቡ ተማሪዎች:\n"
                for r in await c.fetchall(): res += f"ID: <code>{r[0]}</code> | {r[1]} | {r[2]}\n"
                await update.message.reply_text(res, parse_mode='HTML')

        elif cmd == "keep2":
            async with db.execute("SELECT * FROM active_paths") as c:
                res = "🔍 ንቁ ውድድሮች:\n"
                for p in await c.fetchall(): res += f"ቦታ: {p[1]} | በ: {p[2]} | {p[3]}\n"
                await update.message.reply_text(res if len(res) > 20 else "ምንም ንቁ ውድድር የለም")

async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    status = "✅ ቦቱ አብርቷል" if m.new_chat_member.status == "member" else "❌ ቦቱ አጥፍቷል"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, f"{status}\nበ: {u.first_name} (ID: {u.id})")

async def init_main():
    await init_db()

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_main())
    
    app_bot = Application.builder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "unmute2", "unblock", "stop2", "oppt", "opptt", "log", "info", "keep2"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    
    keep_alive()
    print("Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
