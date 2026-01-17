import os, json, asyncio, random, aiosqlite, re
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server ---
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
            (user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0, is_muted INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_paths 
            (chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_id INTEGER, starter_name TEXT, start_time TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)''')
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
    if not user or user[4] != 'approved' or user[5] == 1: return
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        # 8, 4, 1.5 logic
        points = 8 if (is_correct and p_data[1] == 0) else (4 if is_correct else 1.5)
        
        if is_correct and p_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs VALUES (?, ?, ?, ?, ?)", (ans.user.id, ans.user.first_name, "✓" if is_correct else "X", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# --- User & Admin Logic ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)
    cmd = update.message.text.split('@')[0].lower()

    # 10. Oppt Check
    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ይህ ቦት ከአድሚን በሰጠው ትእዛዝ መሰረት እስኪታዘዝ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
        return

    # 12. Registration Logic
    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, full_name, status) VALUES (?, ?, ?, 'pending')", (user.id, user.username, user.full_name))
            await db.commit()
        await update.message.reply_text(f"ውድ ተማሪ {user.full_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው ተቀባይነት እንዳገኘ የምናሳውቅዎ ይሆናል")
        for adm in ADMIN_IDS:
            await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.full_name}\nID: {user.id}\nUsername: @{user.username}\n\nለመቀበል: /approve {user.id}")
        return

    if u_data[4] == 'pending':
        await update.message.reply_text(f"ውድ ተማሪ {user.full_name} አድሚኑ ፈቃድ እስከሚሰጥዎ ድረስ እባክዎ በትዕግስት ይጠብቁ\nለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if u_data[5] == 1: return # Blocked user

    # 15. Command Security (Group vs Private)
    if chat.type == "private":
        allowed_p = ["/start", "/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]
        if cmd not in allowed_p and user.id not in ADMIN_IDS:
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
            await update.message.reply_text(f"የህግ ጥሰት: ከተፈቀደልዎ ትእዛዝ ውጭ አዘዋል\nከ {ADMIN_USERNAME}")
            for adm in ADMIN_IDS:
                await context.bot.send_message(adm, f"🚫 ተማሪ በህግ ጥሰት ታግዷል:\nስም: {user.full_name}\nID: {user.id}\nUsername: @{user.username}")
            return
    else:
        allowed_g = ["/start2", "/stop2"]
        if cmd not in allowed_g and user.id not in ADMIN_IDS: return

    # 3. Start2 Message for Group
    if cmd == "/start2" and chat.type != "private":
        await update.message.reply_text("ዉድ ተማሪዎች ውድድር መጀመሩን እየገፅን ቀድሞ ለመለሰ 8ነጥብ ሌላ ላገኘ 4ነጥብ ለተሳተፉ 1.5ነጥብ ያገኛሉ")

    # Quiz Starter
    sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
    st_time = datetime.now().strftime("%H:%M")
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private User", user.id, user.full_name, st_time))
        await db.commit()

    jobs = context.job_queue.get_jobs_by_name(str(chat.id))
    for j in jobs: j.schedule_removal()
    context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))

# --- Admin Controls ---
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    msg = update.message
    txt = msg.text.split()
    cmd = txt[0][1:].lower()
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        # Extract ID from reply or argument
        target_id = None
        if msg.reply_to_message:
            found = re.search(r'ID: (-?\d+)', msg.reply_to_message.text)
            if found: target_id = int(found.group(1))
        elif len(txt) > 1:
            target_id = int(txt[1])

        # 12. Approve/Anapprove
        if cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
            u = await get_user(target_id)
            await context.bot.send_message(target_id, f"ውድ ተማሪ {u[2]} ጥያቄዎ ተቀባይነት አግኝቷል ለመጀመር መግለጫው ላይ ያሉትን ትእዛዞች ይዘዙ")
            await msg.reply_text(f"ተጠቃሚ {target_id} ጸድቋል")

        elif cmd == "anapprove" and target_id:
            u = await get_user(target_id)
            await db.execute("DELETE FROM users WHERE user_id = ?", (target_id,))
            await db.commit()
            await context.bot.send_message(target_id, f"ውድ ተማሪ {u[2] if u else ''} ይቅርታ ጥያቄዎ ተቀባይነት አላገኘም እባክዎ ደግመው ይሞክሩ ከ {ADMIN_USERNAME}")

        # 6. Block/Unblock
        elif cmd == "block" and target_id:
            if target_id > 0: # User
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target_id,))
                u = await get_user(target_id)
                await context.bot.send_message(target_id, f"ውድ ተማሪ {u[2] if u else ''} ከአድሚኑ በኩል በተላለፈ ትእዛዝ መሰረት ይህን ቦት እንዳይጠቀሙ ታግደዋል, ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ እናመሰግናለን")
            else: # Group
                await context.bot.send_message(target_id, f"ውድ የዚህ group አባል ከአድሚን በተሰጠው ትእዛዝ መሰረት ይህ ቦት እዚህ group ላይ እንዳይሰራ ታግዷል {ADMIN_USERNAME}")
            await db.commit()
            await msg.reply_text(f"ID {target_id} ታግዷል")

        elif cmd == "unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (target_id,))
            await db.commit()
            if target_id > 0:
                u = await get_user(target_id)
                await context.bot.send_message(target_id, f"ውድ ተማሪ {u[2] if u else ''} የነበረብዎ ችግር ስለተፈታ አሁን መጠቀም ይችላል")
            else:
                await context.bot.send_message(target_id, f"ይህ group ከ ቦቱ ጋር የነበረበት ችግር ስለተፈታ አሁን መጠቀም ይችላሉ {ADMIN_USERNAME}")

        # 6. Close
        elif cmd == "close" and target_id:
            for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await context.bot.send_message(target_id, f"ከአድሚን በመጣ ትእዛዝ መሰረት ቦቱ ቆሟል\nለበለጠ መረጃ {ADMIN_USERNAME}")

        # 1. Keep
        elif cmd == "keep":
            async with db.execute("SELECT * FROM active_paths") as c:
                paths = await c.fetchall()
                if not paths: await msg.reply_text("ምንም ንቁ መንገድ የለም")
                for p in paths: await msg.reply_text(f"📍 ቦታ: {p[1]}\nID: {p[0]}\nበ: {p[3]}\nሰዓት: {p[4]}")

        # 2. Stop2
        elif cmd == "stop2":
            for j in context.job_queue.get_jobs_by_name(str(msg.chat_id)): j.schedule_removal()
            if msg.chat.type == "private":
                u = await get_user(msg.from_user.id)
                await msg.reply_text(f"ውድድር ቆሟል! የእርስዎ ነጥብ: {u[3]} pts")
            else:
                async with db.execute("SELECT full_name, points FROM users ORDER BY points DESC LIMIT 15") as c:
                    res = "📊 Best of 15:\n" + "\n".join([f"{i+1}. {r[0]} - {r[1]}" for i, r in enumerate(await c.fetchall())])
                    await msg.reply_text(res)

        # 4. Rank2
        elif cmd == "rank2":
            if msg.chat.type == "private":
                u = await get_user(msg.from_user.id)
                await msg.reply_text(f"የእርስዎ ነጥብ: {u[3]} pts")
            else:
                async with db.execute("SELECT full_name, points FROM users ORDER BY points DESC") as c:
                    res = "📊 የሁሉንም ተወዳዳሪ ነጥብ:\n" + "\n".join([f"{r[0]}: {r[1]}" for r in await c.fetchall()])
                    await msg.reply_text(res)

        # 8, 9. Logs
        elif cmd == "log":
            async with db.execute("SELECT * FROM logs ORDER BY date DESC, timestamp DESC LIMIT 30") as c:
                res = "📜 Log (✓/X):\n" + "\n".join([f"{r[4]} {r[3]} | {r[1]} {r[2]}" for r in await c.fetchall()])
                await msg.reply_text(res)
        elif cmd == "clear_log":
            await db.execute("DELETE FROM logs")
            await db.commit()
            await msg.reply_text("♻️ Log ተጠርጓል")

        # 10, 11. Oppt/Opptt
        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await msg.reply_text("ቦቱ ለሁሉም ቆሟል")
        elif cmd == "opptt":
            GLOBAL_STOP = False
            await msg.reply_text("ቦቱ ወደ ስራ ተመልሷል")

        # 13, 14. Info & Hmute
        elif cmd == "hmute":
            async with db.execute("SELECT user_id, username, full_name, is_blocked, is_muted FROM users WHERE is_blocked=1 OR is_muted=1") as c:
                for r in await c.fetchall():
                    s = "blocked" if r[3] == 1 else "muted"
                    await msg.reply_text(f"👤 {r[2]}\nID: {r[0]}\nUser: @{r[1]}\nStatus: {s}")
        elif cmd == "info":
            async with db.execute("SELECT COUNT(*) FROM users") as c: count = (await c.fetchone())[0]
            await msg.reply_text(f"📊 ተመዝጋቢ: {count}")
            async with db.execute("SELECT * FROM active_paths") as c:
                for r in await c.fetchall(): await msg.reply_text(f"🏢 Group: {r[1]}\nID: {r[0]}")

async def status_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    txt = f"{'✅ ቦቱ አብርቷል' if m.new_chat_member.status == 'member' else '❌ ቦቱ አጥፍቷል'}\nበ: {u.full_name} ({u.id})"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, txt)

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start", "start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "unblock", "close", "keep", "stop2", "rank2", "clear_rank2", "log", "clear_log", "oppt", "opptt", "hmute", "info"], admin_cmd))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_update, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
