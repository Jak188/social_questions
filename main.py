import os, json, asyncio, random, aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server for Render (Uptime) ---
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
        # ጥያቄዎቹን ከ questions.json ፋይል ያነባል
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
            subject = job.data.get('subject')
            questions = [q for q in all_q if q.get('subject', '').lower() == subject.lower()] if subject else all_q
            if not questions: return
            q = random.choice(questions)
            msg = await context.bot.send_poll(job.chat_id, f"[{q.get('subject', 'General')}] {q['q']}", q['o'], 
                is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', ''))
            
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (?, ?, ?)", 
                                 (msg.poll.id, int(q['c']), job.chat_id))
                await db.commit()
    except Exception as e:
        print(f"Quiz Error: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_data = await get_user(ans.user.id)
    if not user_data or user_data[3] != 'approved' or user_data[4] == 1: return
    
    # የሙት (Mute) ጊዜን መፈተሽ
    if user_data[5]:
        if datetime.now(timezone.utc) < datetime.fromisoformat(user_data[5]): return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        
        # ነጥብ አሰጣጥ ህግ (8, 4, 1.5)
        points = 0
        if is_correct:
            if p_data[1] == 0: # የመጀመሪያ በትክክል የመለሰ
                points = 8
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
                await context.bot.send_message(p_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
            else:
                points = 4
        else:
            points = 1.5 # ለተሳሳተ ተሳትፎ

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
    text = update.message.text.split('@')[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
        return

    # ምዝገባ
    if not u_data:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, now_str))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው፤ አድሚኑ እስኪቀበልዎ በትእግስት ይጠብቁ")
        for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: {user.id}\nUsername: @{user.username}")
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ፈቃድ እስከሚሰጥዎ ድረስ በትዕግስት ይጠብቁ\nለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if u_data[4] == 1:
        await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል፤ ለበለተ መረጃ {ADMIN_USERNAME}")
        return

    # የቅጣት ስርዓት
    allowed_private = ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/keep"]
    if chat.type == "private" and text not in allowed_private and user.id not in ADMIN_IDS:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"የህግ ጥሰት: ያልተፈቀደ ትዕዛዝ በመጠቀሞ ታግደዋል።\nለማንሳት {ADMIN_USERNAME} ያናግሩ")
        return

    # ውድድር ማስጀመሪያ
    if text in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
        sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(text)
        now = datetime.now()
        
        # ለአድሚን ማሳወቅ
        inf = f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name} (ID: {user.id})\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {now.strftime('%H:%M:%S')}"
        for adm in ADMIN_IDS: await context.bot.send_message(adm, inf)

        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, now.strftime("%Y-%m-%d %H:%M")))
            await db.commit()

        # አሮጌ ጥያቄ ካለ ማቆም
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        
        # በየ 3 ደቂቃው ጥያቄ መላክ
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))
        await update.message.reply_text("ውድድር መጀመሩን እንገልጻለን! \nቀድሞ ለመለሰ 8 ነጥብ፣ በትክክል ለመለሰ 4 ነጥብ፣ ለተሳተፈ 1.5 ነጥብ ይሰላል።")

# --- Admin Controls ---
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
            await context.bot.send_message(target, "ውድ ተማሪ ምዝገባዎ ጸድቋል! አሁን መሳተፍ ይችላሉ።")
            await update.message.reply_text(f"ተጠቃሚ {target} ጸድቋል")

        elif cmd == "log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY date DESC, timestamp DESC LIMIT 20") as c:
                res = "📜 የሁሉንም ተወዳዳሪ ስህተት እና ልክነት ዝርዝር:\n"
                for r in await c.fetchall(): res += f"{r[2]} {r[3]} | {r[0]} {r[1]}\n"
                await update.message.reply_text(res if len(res)>25 else "ምንም መዝገብ የለም")

        elif cmd == "rank2":
            async with db.execute("SELECT username, points FROM users WHERE status='approved' ORDER BY points DESC LIMIT 15") as c:
                res = "🏆 ምርጥ 15 ተወዳዳሪዎች:\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} ነጥብ\n"
                await update.message.reply_text(res)

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await update.message.reply_text(f"ቦቱ በአድሚን ትዕዛዝ ቆሟል @penguiner")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await update.message.reply_text("ቦቱ ስራ ጀምሯል")

async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    status = "✅ ቦቱ አብርቷል" if m.new_chat_member.status == 'member' else "❌ ቦቱ አጥፍቷል"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, f"{status}\nበ: {u.first_name} (ID: {u.id})")

def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    
    app_bot = Application.builder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "unblock", "unmute2", "stop2", "oppt", "opptt", "log", "hmute", "info", "keep2", "rank2", "clear_rank2"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__':
    main()
