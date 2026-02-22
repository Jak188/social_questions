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

# ===================== CONFIG (የአንተ መረጃዎች) =====================
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
            muted_until TEXT, reg_at TEXT)""")
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

async def broadcast_msg(context, text):
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT user_id FROM users") as c: usrs = await c.fetchall()
        async with db.execute("SELECT chat_id FROM active_paths") as c: grps = await c.fetchall()
    all_targets = {u[0] for u in usrs} | {g[0] for g in grps}
    for tid in all_targets:
        try: await context.bot.send_message(tid, f"{text}\n\nOwner: {ADMIN_USERNAME}", parse_mode="HTML")
        except: pass

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
    if u[5] and datetime.now(timezone.utc) < datetime.fromisoformat(u[5]): return

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
            else:
                pts = 4
        else:
            pts = 1.5

        await db.execute("UPDATE users SET points = points + ? WHERE user_id=?", (pts, user_id))
        now = datetime.now()
        await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (user_id, ans.user.first_name, "✔️" if is_correct else "❎", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# ===================== USER HANDLERS =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not update.message: return
    cmd = update.message.text.split()[0].split("@")[0].lower()

    # Global Stop Check
    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    u = await get_user(user.id)

    # 1. Registration Logic
    if not u:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("INSERT INTO users(user_id, username, reg_at) VALUES(?,?,?)", (user.id, user.first_name, now_str))
            await db.commit()
        await update.message.reply_text(f"👋 ውድ {user.first_name}\nምዝገባዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ ድረስ እባክዎ በትዕግስት ይጠብቁ።")
        for a in ADMIN_IDS:
            await context.bot.send_message(a, f"👤 አዲስ ተመዝጋቢ: {user.first_name}\nID: <code>{user.id}</code>\n/approve reply adrgu", parse_mode="HTML")
        return

    if u[3] == 'pending':
        await update.message.reply_text(f"⏳ ውድ {user.first_name} አድሚኑ ለጊዜው ቢዚ ነው። ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን። እናመሰግናለን!")
        return

    if u[4] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ መሰረት ለጊዜው ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ።")
        return

    # 2. Command Security (Mute/Block Logic)
    allowed_p = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2","/rank2","/stop2"]
    
    # Private Chat Security
    if chat.type == "private" and cmd not in allowed_p and user.id not in ADMIN_IDS:
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"⚠️ የህግ ጥሰት! በግል እንዲጠቀሙ ያልተፈቀደ ትዕዛዝ በመጠቀሞ ታግደዋል። {ADMIN_USERNAME}")
        return

    # Group Chat Security
    if chat.type != "private" and cmd.startswith("/") and cmd not in ["/start2","/stop2"] and user.id not in ADMIN_IDS:
        m_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until=? WHERE user_id=?", (m_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} ህግ ጥሰዋል! 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል። {ADMIN_USERNAME}")
        for a in ADMIN_IDS:
            await context.bot.send_message(a, f"⚠️ Mute (Group): {user.first_name} በግሩፕ ውስጥ ያልተፈቀደ ትዕዛዝ ተጠቅሟል።\nID: <code>{user.id}</code>\n/unmute2 reply adrgu", parse_mode="HTML")
        return

    # 3. Logic for Commands
    if cmd == "/stop2":
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("DELETE FROM active_paths WHERE chat_id=?", (chat.id,))
            await db.commit()
        res = "🛑 ውድድር ቆሟል።\n"
        if chat.type == "private": res += f"የግል ነጥብዎ: {u[2]}"
        else:
            res += "\n📊 Best 15 Rankings:\n"
            async with aiosqlite.connect("quiz_bot.db") as db:
                async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                    for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(res)
        for a in ADMIN_IDS: await context.bot.send_message(a, f"🛑 Stop: {chat.title or 'Private'}\nBy: {user.first_name} ({user.id})")
        return

    if cmd in allowed_p or cmd == "/start2":
        s_map = {"/history_srm2":"history","/geography_srm2":"geography","/mathematics_srm2":"mathematics","/english_srm2":"english"}
        sub = s_map.get(cmd, "All")
        await update.message.reply_text(f"🚀 የ {sub} ውድድር ተጀምሯል! (በየ 3 ደቂቃ)\nቀድሞ ለመለሰ 8 | በትክክል 4 | ለተሳተፈ 1.5 ነጥብ")
        
        now_t = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, now_t, sub))
            await db.commit()
        
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={"subject": sub}, name=str(chat.id))
        for a in ADMIN_IDS: 
            await context.bot.send_message(a, f"🚀 Start: {chat.title or 'Private'}\nBy: {user.first_name} (ID: {user.id})\nSubject: {sub}\nTime: {now_t}")

    if cmd == "/rank2":
        async with aiosqlite.connect("quiz_bot.db") as db:
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 20") as c:
                res = "🏆 Rankings:\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(res)

# ===================== ADMIN LOGIC =====================
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    m = update.message
    args = m.text.split()
    cmd = args[0][1:].lower()
    target_id = None

    # Handle Replay or ID Argument
    if m.reply_to_message:
        match = re.search(r"ID: (\d+)|ID:<code>(\d+)</code>", m.reply_to_message.text)
        if match: target_id = int(match.group(1) or match.group(2))
    elif len(args) > 1:
        try: target_id = int(args[1])
        except: pass

    async with aiosqlite.connect("quiz_bot.db") as db:
        if cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, f"✅ ምዝገባዎ ተቀባይነት አግኝቷል። አሁን መወዳደር ይችላሉ!\n{ADMIN_USERNAME}")
            except: pass
            await m.reply_text(f"User {target_id} Approved ✅")
        
        elif cmd == "anapprove" and target_id:
            await db.execute("DELETE FROM users WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "❌ የምዝገባ ጥያቄዎ ውድቅ ሆኗል። እባክዎ እንደገና ይሞክሩ።")
            except: pass
            await m.reply_text("Rejected ❌")

        elif cmd == "block" and target_id:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። {ADMIN_USERNAME}")
            except: pass
            await m.reply_text("Blocked 🚫")

        elif cmd == "unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል።")
            except: pass
            await m.reply_text("Unblocked ✅")

        elif cmd == "unmute2" and target_id:
            await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?", (target_id,))
            async with db.execute("SELECT username FROM users WHERE user_id=?", (target_id,)) as c: r = await c.fetchone()
            await db.commit()
            name = r[0] if r else "ተማሪ"
            await m.reply_text(f"ተማሪ {name} እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ።")
            try: await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል።")
            except: pass

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await broadcast_msg(context, f"⛔️ ቦቱ ከአድሚን በመጣ ትዕዛዝ ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")
            await m.reply_text("Global Stop Active")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await broadcast_msg(context, "✅ ቦቱ ተመልሷል። አሁን መወዳደር ትችላላችሁ።")
            await m.reply_text("Global Stop Removed")

        elif cmd == "log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 50") as c:
                res = "📜 Logs (Recent 50):\n"
                for r in await c.fetchall(): res += f"{r[2]} {r[3]} | {r[0]} {r[1]}\n"
            await m.reply_text(res or "No logs.")

        elif cmd == "clear_log":
            await db.execute("DELETE FROM logs")
            await db.commit()
            await m.reply_text("Logs Cleared 🧹")

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username FROM users") as c:
                res = "👥 ተመዝጋቢዎች:\n"
                rows = await c.fetchall()
                for r in rows: res += f"ID: <code>{r[0]}</code> | {r[1]}\n"
                res += f"\nTotal: {len(rows)}"
            await m.reply_text(res, parse_mode="HTML")

        elif cmd == "info" and target_id:
            async with db.execute("SELECT * FROM users WHERE user_id=?", (target_id,)) as c:
                u = await c.fetchone()
                if u:
                    txt = f"🆔 ID: {u[0]}\n👤 Name: {u[1]}\n⭐ Pts: {u[2]}\n🚦 Status: {u[3]}\n🚫 Blocked: {'Yes' if u[4] else 'No'}\n📅 Reg: {u[6]}"
                    await m.reply_text(txt)

        elif cmd == "keep":
            async with db.execute("SELECT * FROM active_paths") as c:
                res = "📡 Active Competitions:\n"
                for r in await c.fetchall(): res += f"📍 {r[1]} | 👤 {r[2]} | ⏰ {r[3]} | 📚 {r[4]}\n"
            await m.reply_text(res or "No active paths.")

        elif cmd == "hmute":
            async with db.execute("SELECT user_id, username, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 Blocked/Muted List:\n"
                for r in await c.fetchall():
                    s = "Blocked" if r[2] == 1 else "Muted"
                    res += f"ID: <code>{r[0]}</code> | {r[1]} | {s}\n"
            await m.reply_text(res or "None", parse_mode="HTML")

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points = 0")
            await db.commit()
            await m.reply_text("Ranks Cleared 0️⃣")

        elif cmd == "close" and target_id:
            for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?", (target_id,))
            await db.commit()
            await m.reply_text(f"Closed quiz on {target_id}")

        elif cmd == "gof":
            async with db.execute("SELECT user_id, username FROM users WHERE status='pending'") as c:
                res = "⏳ የሚጠብቁ (Pending):\n"
                for r in await c.fetchall(): res += f"ID: <code>{r[0]}</code> | {r[1]}\n"
            await m.reply_text(res or "Empty", parse_mode="HTML")

# ===================== NOTIFICATIONS =====================
async def chat_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    chat = update.effective_chat
    u = update.effective_user
    st = "✅ ቦቱ በርቷል" if m.new_chat_member.status in ["member", "administrator"] else "❌ ቦቱ ጠፍቷል"
    for a in ADMIN_IDS: 
        await context.bot.send_message(a, f"{st}\nBy: {u.first_name}\nChat: {chat.title or 'Private'}\nID: {chat.id}")

# ===================== MAIN =====================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    keep_alive()
    
    bot_app = Application.builder().token(TOKEN).build()
    
    # Handlers
    bot_app.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2","rank2"], start_handler))
    bot_app.add_handler(CommandHandler(["approve","anapprove","block","unblock","unmute2","log","clear_log","oppt","opptt","pin","keep","hmute","info","clear_rank2","close","gof"], admin_ctrl))
    bot_app.add_handler(PollAnswerHandler(receive_answer))
    bot_app.add_handler(ChatMemberHandler(chat_status, ChatMemberHandler.MY_CHAT_MEMBER))
    
    print("Bot is running...")
    bot_app.run_polling()

if __name__ == "__main__":
    main()
