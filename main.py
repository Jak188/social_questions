import os, json, asyncio, random, aiosqlite
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
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, timestamp TEXT)''')
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
        # 28. ነጥብ አሰጣጥ (8, 4, 1.5)
        points = 8 if (is_correct and p_data[1] == 0) else (4 if is_correct else 1.5)
        
        if is_correct and p_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp) VALUES (?, ?, ?, ?)", (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", datetime.now().strftime("%H:%M:%S")))
        await db.commit()

# --- Core Logic ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    # 21. Global Stop (oppt)
    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ለታወቀ ጊዜ ተቆጥቧል ለበለተ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
        return

    # 1, 5, 6. Registration
    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው ጥያቄውን አድሚኑ እስኪቀበልዎ እባክዎ በትእግስት ይጠብቁ")
        for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: {user.id}\nለማጽደቅ: /approve {user.id}\nለመከልከል: /anapprove {user.id}")
        return

    if u_data[3] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው ቢዚ ነው ጥያቄዎ ተቀባይነት ሲያገኝ የምናሳውቅዎ ይሆናል እናመሰግናለን")
        return

    if u_data[4] == 1:
        await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለተ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
        return

    # 4, 30. Group Rule & Mute
    cmd = update.message.text.split('@')[0].lower()
    if chat.type != "private" and user.id not in ADMIN_IDS:
        mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
            await db.commit()
        await update.message.reply_text(f"የህግ ጥሰት.. {user.first_name} የአድሚን ትእዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል ለ17 ደቂቃ ታግደሃል")
        return

    # 29. Private security
    if chat.type == "private" and cmd not in ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/keep"] and user.id not in ADMIN_IDS:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"የህግ ጥሰት.. ለብቻህ በግል የተከለከለ ትእዛዝ በመጠቀክህ በቋሚነት ታግደሃል {ADMIN_USERNAME} ን ያናግሩ")
        return

    # 10-14, 31. Start Quiz
    sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
    n = datetime.now()
    inf = f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name} (ID: {user.id})\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {n.strftime('%H:%M')} | ቀን: {n.strftime('%Y-%m-%d')}"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, inf)

    jobs = context.job_queue.get_jobs_by_name(str(chat.id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, data={'subject': sub, 'starter': user.first_name}, name=str(chat.id))
    await update.message.reply_text(f"🚀 የ{sub if sub else 'Random'} ውድድር ተጀመረ!")

# --- Admin Functions ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        target = update.message.reply_to_message.from_user.id if update.message.reply_to_message else (int(txt[1]) if len(txt)>1 else None)

        if cmd == "approve" and target:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target,))
            await db.commit()
            await context.bot.send_message(target, "✅ እንኳን ደስ አለዎት! ምዝገባዎ ተቀባይነት አግኝቷል መሳተፍ ይችላሉ።")
            await update.message.reply_text(f"ተጠቃሚ {target} ጸድቋል")
        
        elif cmd == "anapprove" and target:
            await db.execute("DELETE FROM users WHERE user_id = ?", (target,))
            await db.commit()
            await context.bot.send_message(target, "❌ ጥያቄዎ ተቀባይነት አላገኘም እባክዎ እንደገና ይሞክሩ")

        elif cmd in ["block", "close"] and target:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target,))
            await db.commit()
            await update.message.reply_text("አልታወቀም ይላል... ምንም")
            await context.bot.send_message(target, f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለተ መረጃ {ADMIN_USERNAME} ን ያናግሩ")

        elif cmd == "unblock" and target:
            await db.execute("UPDATE users SET is_blocked = 0, status='approved' WHERE user_id = ?", (target,))
            await db.commit()
            await update.message.reply_text("እገዳው ተነስቷል")

        elif cmd == "unmute" and update.message.reply_to_message:
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (update.message.reply_to_message.from_user.id,))
            await db.commit()
            await update.message.reply_text("🔊 ማስጠንቀቂያ እገዳው ተነስቷል በስነ ስርአት ይሳተፉ")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            async with db.execute("SELECT username, points FROM users WHERE points > 0 ORDER BY points DESC LIMIT 15") as c:
                rows = await c.fetchall()
                res = "📊 ውጤት (Top 15):\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]} pts" for i,r in enumerate(rows)])
                await update.message.reply_text(res if rows else "ምንም ውጤት የለም")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🏁 ውድድር በ {update.effective_user.first_name} ቆሟል")

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await update.message.reply_text("ቦቱ ለሁሉም ቆሟል")
        elif cmd == "opptt":
            GLOBAL_STOP = False
            await update.message.reply_text("ቦቱ ተከፍቷል")

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username FROM users") as c:
                for r in await c.fetchall(): await context.bot.send_message(update.effective_chat.id, f"👤 {r[1]}\nID: `{r[0]}`")
        
        elif cmd == "keep":
            jobs = context.job_queue.jobs()
            for j in jobs: await context.bot.send_message(update.effective_chat.id, f"🟢 ACTIVE\nID: {j.name}\nበ: {j.data.get('starter')}")

        elif cmd == "rank2":
            u = await get_user(update.effective_user.id)
            await update.message.reply_text(f"📊 የእርስዎ ነጥብ: {u[2] if u else 0}")

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points = 0")
            await db.commit()
            await update.message.reply_text("♻️ ሁሉም ነጥብ ተሰርዟል")

        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 20") as c:
                rows = await c.fetchall()
                await update.message.reply_text("📜 Log:\n" + "\n".join([f"{r[2]} | {r[0]} {r[1]}" for r in rows]))

async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    txt = f"{'✅ ቦቱ አብርቷል' if m.new_chat_member.status == 'member' else '❌ ቦቱ አጥፍቷል'}...\nበ: {u.first_name}"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, txt)

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "close", "unblock", "unmute", "stop2", "oppt", "opptt", "pin", "keep", "rank2", "clear_rank2", "log"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
