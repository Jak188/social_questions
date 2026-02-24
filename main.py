import os, json, asyncio, random, re, logging
import aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, ChatMemberHandler, filters, MessageHandler
)

# ===================== CONFIG =====================
TOKEN = "8195013346:AAEyh3J8Q5kLtHPNzo_H-qral_sXMiCfA04"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== FLASK (KEEP ALIVE) =====================
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== DATABASE INIT =====================
async def init_db():
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0,
            status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0,
            muted_until TEXT, reg_at TEXT, last_active TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS active_polls(
            poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS logs(
            user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS active_paths(
            chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT, subject TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS asked_questions(
            chat_id INTEGER, question_text TEXT)""")
        await db.commit()

# ===================== UTILS =====================
async def get_user(user_id):
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone()

async def update_activity(user_id):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute("UPDATE users SET last_active=? WHERE user_id=?", (now, user_id))
        await db.commit()

# ===================== QUIZ ENGINE =====================
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    chat_id = job.chat_id
    sub = job.data.get("subject")

    try:
        with open("questions.json", "r", encoding="utf-8") as f: all_q = json.load(f)
        filtered = [q for q in all_q if not sub or sub == "All" or q.get("subject","").lower() == sub.lower()]
        
        async with aiosqlite.connect("quiz_bot.db") as db:
            async with db.execute("SELECT question_text FROM asked_questions WHERE chat_id=?", (chat_id,)) as c:
                asked = [r[0] for r in await c.fetchall()]
            
            remaining = [q for q in filtered if q['q'] not in asked]
            if not remaining:
                await db.execute("DELETE FROM asked_questions WHERE chat_id=?", (chat_id,))
                remaining = filtered
            
            if not remaining: return
            q = random.choice(remaining)
            msg = await context.bot.send_poll(
                chat_id, f"📚 [{q.get('subject','General')}] {q['q']}", q["o"],
                type=Poll.QUIZ, is_anonymous=False, correct_option_id=int(q["c"]),
                explanation=q.get("exp","")
            )
            await db.execute("INSERT INTO active_polls VALUES(?,?,?,0)", (msg.poll.id, int(q["c"]), chat_id))
            await db.execute("INSERT INTO asked_questions VALUES(?,?)", (chat_id, q['q']))
            await db.commit()
    except Exception as e: print(f"Quiz Error: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    u = await get_user(user_id)
    
    if not u or u[3] != 'approved' or u[4] == 1: return
    await update_activity(user_id)

    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c:
            poll = await c.fetchone()
        if not poll: return

        is_correct = ans.option_ids[0] == poll[0]
        if is_correct:
            if poll[1] == 0:
                pts = 8
                await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (user_id, ans.poll_id))
                await context.bot.send_message(poll[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ በትክክል በመመለሱ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
            else: pts = 4
        else: pts = 1.5

        await db.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, user_id))
        now = datetime.now()
        action = "✔️" if is_correct else "❎"
        await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (user_id, ans.user.first_name, action, now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# ===================== MAIN HANDLER =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not update.message: return
    cmd = update.message.text.split()[0].split("@")[0].lower()

    u = await get_user(user.id)

    if cmd == "/rank2":
        async with aiosqlite.connect("quiz_bot.db") as db:
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 20") as c:
                res = "🏆 ደረጃ እና ነጥብ:\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(res)
        return

    if u and u[4] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ መሰረት ለጊዜው ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
        return
    
    if u and u[5]:
        try:
            m_until = datetime.fromisoformat(u[5])
            if datetime.now(timezone.utc) < m_until:
                return
        except: pass

    if chat.type != "private" and cmd.startswith("/") and cmd not in ["/start2","/stop2"] and user.id not in ADMIN_IDS:
        m_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until=? WHERE user_id=?", (m_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} በግሩፕ ውስጥ ያልተፈቀደ ትዕዛዝ በመጠቀምዎ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ቦቱ ከአድሚን በመጣ ትዕዛዝ ለተወሰነ ጊዜ ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if not u:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect("quiz_bot.db") as db:
            uname = f"{user.first_name} (@{user.username})" if user.username else user.first_name
            await db.execute("INSERT INTO users(user_id, username, reg_at, status) VALUES(?,?,?,'pending')", (user.id, user.first_name, now_str))
            await db.commit()
        await update.message.reply_text(f"👋 ውድ ተማሪ {user.first_name}\nምዝገባዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ ድረስ እባክዎ በትዕግስት ይጠብቁ።")
        for a in ADMIN_IDS: await context.bot.send_message(a, f"👤 አዲስ ተመዝጋቢ:\nID: <code>{user.id}</code>\nስም: {user.first_name}\n/approve {user.id}", parse_mode="HTML")
        return

    if u[3] == 'pending':
        await update.message.reply_text(f"⏳ ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው busy ነው ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን እናመሰግናለን።")
        return

    if u[7]:
        last_active = datetime.fromisoformat(u[7])
        if datetime.now(timezone.utc) - last_active > timedelta(hours=29):
            await update.message.reply_text(f"⚠️ ውድ ተማሪ {user.first_name} የተሳትፎ ሰዓትዎ በጣም ስለቆየ ሲስተሙ አግዶዎታል እገዳዎትን ለማስነሳት {ADMIN_USERNAME} ን ይጠይቁ : እናመሰግናለን")
            return

    start_cmds = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2"]
    all_allowed = start_cmds + ["/stop2", "/rank2"]

    if chat.type == "private" and cmd not in all_allowed and user.id not in ADMIN_IDS:
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"⚠️ የህግ ጥሰት! ያልተፈቀደ ትዕዛዝ በመጠቀሞ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        for a in ADMIN_IDS: await context.bot.send_message(a, f"🚫 Blocked: {user.first_name} (ID: {user.id}) በግል የተከለከለ ትዕዛዝ በማዘዙ።")
        return

    if cmd == "/stop2":
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("DELETE FROM active_paths WHERE chat_id=?", (chat.id,))
            await db.commit()
        res = "🛑 ውድድር ቆሟል።\n"
        if chat.type == "private":
            res += f"የግል ነጥብዎ: {u[2]}"
        else:
            async with aiosqlite.connect("quiz_bot.db") as db:
                async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                    res += "\n📊 Best 15:\n"
                    for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(res)
        for a in ADMIN_IDS: await context.bot.send_message(a, f"🛑 Stop: {chat.title or 'Private'} | በ: {user.first_name}")
        return

    if cmd in start_cmds:
        s_map = {"/history_srm2":"history","/geography_srm2":"geography","/mathematics_srm2":"mathematics","/english_srm2":"english"}
        sub = s_map.get(cmd, "All")
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        await update.message.reply_text(f"🚀 የ {sub} ውድድር ተጀምሯል! በየ 3 ደቂቃ ጥያቄ ይላካል።")
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={"subject": sub}, name=str(chat.id))
        now_t = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, now_t, sub))
            await db.commit()
        for a in ADMIN_IDS: await context.bot.send_message(a, f"🚀 Start: {chat.title or 'Private'} | በ: {user.first_name} | {sub}")

# ===================== ADMIN SYSTEM =====================
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_STOP
    if update.effective_user.id not in ADMIN_IDS: return
    m = update.message
    cmd = m.text.split()[0][1:].lower()
    target_id = None

    # 1. መጀመሪያ ውድድሩን የመዝጊያ ትዕዛዝ (Reply ላይ ካልተመሰረተም እንዲሰራ)
    if cmd == "close":
        for j in context.job_queue.get_jobs_by_name(str(m.chat_id)):
            j.schedule_removal()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("DELETE FROM active_paths WHERE chat_id=?", (m.chat_id,))
            await db.commit()
        await m.reply_text("🛑 ውድድሩ በአድሚን ትዕዛዝ ቆሟል።")
        return

    # 2. የID ፍለጋ (ከ close ትዕዛዝ ውጭ መሆን አለበት)
    if m.reply_to_message:
        match = re.search(r"ID: (\d+)|ID:<code>(\d+)</code>", m.reply_to_message.text)
        if match: 
            target_id = int(match.group(1) or match.group(2))
    
    # በጽሑፍ ID ከተላከ (ለምሳሌ /approve 12345)
    if not target_id and len(m.text.split()) > 1:
        try: target_id = int(m.text.split()[1])
        except: pass

    async with aiosqlite.connect("quiz_bot.db") as db:
        if cmd == "gof":
            async with db.execute("SELECT user_id, username, reg_at FROM users WHERE status='pending'") as c:
                rows = await c.fetchall()
                if not rows:
                    await m.reply_text("የምዝገባ ጥያቄ ያቀረበ አዲስ ተማሪ የለም።")
                    return
                res = "📝 የምዝገባ ጥያቄ ያቀረቡ ተማሪዎች ዝርዝር፦\n\n"
                for r in rows:
                    res += f"👤 ስም: {r[1]}\nID: <code>{r[0]}</code>\nቀን: {r[2]}\n"
                await m.reply_text(res, parse_mode="HTML")

        elif cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?", (target_id,))
            await db.commit()
            await m.reply_text(f"ተማሪ {target_id} ተቀባይነት አግኝቷል ✅")
            try: await context.bot.send_message(target_id, "✅ ምዝገባዎ ተቀባይነት አግኝቷል። አሁን መወዳደር ይችላሉ!")
            except: pass

        elif cmd == "anapprove" and target_id:
            await db.execute("DELETE FROM users WHERE user_id=?", (target_id,))
            await db.commit()
            await m.reply_text(f"ተማሪ {target_id} ውድቅ ተደርጓል ❌")
            try: await context.bot.send_message(target_id, "❌ የምዝገባ ጥያቄዎ ተቀባይነት አላገኘም እባክዎ እንደገና ይሞክሩ።")
            except: pass

        elif cmd == "block" and target_id:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (target_id,))
            await db.commit()
            await m.reply_text(f"🚫 ተማሪ {target_id} ታግዷል።")
            try:
                await context.bot.send_message(
                    chat_id=target_id, 
                    text=f"🚫 **ማሳሰቢያ**\nከአድሚን በመጣ ትዕዛዝ መሰረት ታግደዋል።\nለበለጠ መረጃ: {ADMIN_USERNAME}",
                    parse_mode="HTML"
                )
            except: pass

        elif cmd == "unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (target_id,))
            await db.commit()
            await m.reply_text(f"✅ ተማሪ {target_id} እገዳው ተነስቷል።")
            try:
                await context.bot.send_message(
                    chat_id=target_id, 
                    text="✅ **መልካም ዜና**\nየነበረብዎት እገዳ በአድሚን ትዕዛዝ ተነስቷል። አሁን መወዳደር ይችላሉ!",
                    parse_mode="HTML"
                )
            except: pass

        elif cmd == "oppt":
            GLOBAL_STOP = True
            await m.reply_text("⛔️ Global Stop በርቷል።")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await m.reply_text("✅ Global Stop ተነስቷል።")

        elif cmd == "yam":
            broadcast_text = m.text.replace("/yam", "").strip()
            async with db.execute("SELECT user_id FROM users WHERE status='approved'") as c1:
                users = await c1.fetchall()
            async with db.execute("SELECT chat_id FROM active_paths") as c2:
                groups = await c2.fetchall()
            
            all_targets = set([u[0] for u in users] + [g[0] for g in groups])
            count = 0
            for target in all_targets:
                try:
                    if m.reply_to_message:
                        await context.bot.copy_message(
                            chat_id=target,
                            from_chat_id=m.chat_id,
                            message_id=m.reply_to_message.message_id,
                            caption=broadcast_text if broadcast_text else m.reply_to_message.caption
                        )
                    elif broadcast_text:
                        await context.bot.send_message(chat_id=target, text=broadcast_text)
                    count += 1
                    await asyncio.sleep(0.05)
                except: continue
            await m.reply_text(f"📢 መልእክቱ ለ {count} ተቀባዮች ተልኳል!")

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points = 0")
            await db.commit()
            await m.reply_text("Rankings Cleared 🧹")

# ===================== RUNNER =====================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    keep_alive()
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2","rank2"], start_handler))
    bot_app.add_handler(CommandHandler(["approve","anapprove","block","unblock","unmute2","log","clear_log","oppt","opptt","pin","keep","hmute","info","clear_rank2","close","gof"], admin_ctrl))
    bot_app.add_handler(PollAnswerHandler(receive_answer))
    bot_app.run_polling()

if __name__ == "__main__":
    main()
