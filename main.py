import os, json, asyncio, random, re
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
TOKEN = "8195013346:AAGe1GBW_I3HB6cfY4FwajbsJouJcwCDo08"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== FLASK (KEEP ALIVE) =====================
app = Flask(__name__)
@app.route('/')
def home(): return "Quiz Bot is Online!"

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

async def broadcast(context, text):
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT user_id FROM users") as c: users = await c.fetchall()
        async with db.execute("SELECT chat_id FROM active_paths") as c: groups = await c.fetchall()
    all_ids = {u[0] for u in users} | {g[0] for g in groups}
    for cid in all_ids:
        try: await context.bot.send_message(cid, f"{text}\n\nOwner: {ADMIN_USERNAME}", parse_mode="HTML")
        except: pass

# ===================== QUIZ LOGIC =====================
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    chat_id = job.chat_id
    sub = job.data.get("subject")

    try:
        with open("questions.json", "r", encoding="utf-8") as f: all_q = json.load(f)
        filtered = [q for q in all_q if (not sub or q.get("subject","").lower()==sub)]
        
        async with aiosqlite.connect("quiz_bot.db") as db:
            async with db.execute("SELECT question_text FROM asked_questions WHERE chat_id=?", (chat_id,)) as c:
                asked = [r[0] for r in await c.fetchall()]
            
            remaining = [q for q in filtered if q['q'] not in asked]
            if not remaining: # ሁሉም ከተጠየቁ Reset አድርግ
                await db.execute("DELETE FROM asked_questions WHERE chat_id=?", (chat_id,))
                remaining = filtered
            
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
    user = await get_user(ans.user.id)
    if not user or user[3] != 'approved' or user[4] == 1: return
    if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return

    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c:
            poll = await c.fetchone()
        if not poll: return

        is_correct = ans.option_ids[0] == poll[0]
        if is_correct and poll[1] == 0:
            points = 8
            await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(poll[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ በትክክል መልሶ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
        else:
            points = 4 if is_correct else 1.5

        await db.execute("UPDATE users SET points = points + ? WHERE user_id=?", (points, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (ans.user.id, ans.user.first_name, "✔️" if is_correct else "❎", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# ===================== MAIN HANDLER =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not update.message: return
    cmd = update.message.text.split()[0].split("@")[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ቦቱ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ቆሟል።\nለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    u = await get_user(user.id)
    # ምዝገባ
    if not u:
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("INSERT INTO users(user_id, username, reg_at) VALUES(?,?,?)", 
                            (user.id, user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            await db.commit()
        await update.message.reply_text(f"👋 ውድ {user.first_name}\nምዝገባዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ ድረስ እባክዎ በትዕግስት ይጠብቁ።")
        for a in ADMIN_IDS:
            await context.bot.send_message(a, f"👤 አዲስ ተመዝጋቢ: {user.first_name}\nID: <code>{user.id}</code>\n/approve reply")
        return

    if u[3] == 'pending':
        await update.message.reply_text(f"⏳ ውድ {user.first_name} አድሚኑ ለጊዜው ስራ በዝቶበት ነው። ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን። እናመሰግናለን!")
        return
    if u[4] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ መሠረት ለጊዜው ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያነጋግሩ።")
        return

    # የደህንነት ቁጥጥር (Private)
    allowed_priv = ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/stop2"]
    if chat.type == "private" and cmd not in allowed_priv and user.id not in ADMIN_IDS:
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user.id,))
            await db.commit()
        await update.message.reply_text(f"⚠️ የህግ ጥሰት! ከተፈቀደው ውጭ ትዕዛዝ በመጠቀማችሁ ታግደዋል። {ADMIN_USERNAME}")
        return

    # የደህንነት ቁጥጥር (Group)
    if chat.type != "private" and cmd.startswith("/") and cmd not in ["/start2", "/stop2"] and user.id not in ADMIN_IDS:
        mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("UPDATE users SET points = points - 3.17, muted_until=? WHERE user_id=?", (mute_time, user.id))
            await db.commit()
        await update.message.reply_text(f"⚠️ {user.first_name} በግሩፕ ውስጥ ህግ በመጣስዎ 3.17 ነጥብ ተቀንሷል + ለ17 ደቂቃ ታግደዋል።")
        for a in ADMIN_IDS:
            await context.bot.send_message(a, f"⚠️ Group Violation: {user.first_name}\nID: <code>{user.id}</code>\nGroup: {chat.title}\n/unmute2 reply")
        return

    # ትዕዛዞች
    if cmd == "/stop2":
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("DELETE FROM active_paths WHERE chat_id=?", (chat_id,))
            await db.commit()
        
        res = "🛑 ውድድር ቆሟል።\n"
        if chat.type == "private":
            res += f"👤 የእርስዎ ነጥብ: {u[2]} pts"
        else:
            res += "\n📊 የደረጃ ሰንጠረዥ (ምርጥ 15):\n"
            async with aiosqlite.connect("quiz_bot.db") as db:
                async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                    for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(res)
        for a in ADMIN_IDS: await context.bot.send_message(a, f"🛑 ውድድር ቆመ በ: {chat.title or 'Private'}\nያቆመው: {user.first_name}")
        return

    if cmd in allowed_priv or cmd == "/start2":
        sub_map = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}
        sub = sub_map.get(cmd)
        await update.message.reply_text(f"🚀 ውድድር ተጀምሯል! (በየ 3 ደቂቃ ጥያቄ ይላካል)\n8 ነጥብ | 4 ነጥብ | 1.5 ነጥብ\nመልካም እድል!")
        
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?,?)", 
                            (chat_id, chat.title or "Private", user.first_name, start_time, sub or "All"))
            await db.commit()
        
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat_id, data={"subject": sub}, name=str(chat_id))
        for a in ADMIN_IDS:
            await context.bot.send_message(a, f"🚀 ውድድር ተጀመረ!\nቦታ: {chat.title or 'Private'}\nበ: {user.first_name} (ID: {user.id})\nሰዓት: {start_time}")

    if cmd == "/rank2":
        async with aiosqlite.connect("quiz_bot.db") as db:
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 20") as c:
                res = "🏆 የደረጃ ሰንጠረዥ:\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(res)

# ===================== ADMIN COMMANDS =====================
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    msg = update.message
    txt = msg.text.split()
    cmd = txt[0][1:].lower()
    target_id = None

    # Reply Logic
    if msg.reply_to_message:
        match = re.search(r"ID: (\d+)|ID:<code>(\d+)</code>", msg.reply_to_message.text)
        if match: target_id = int(match.group(1) or match.group(2))
    elif len(txt) > 1:
        try: target_id = int(txt[1])
        except: pass

    async with aiosqlite.connect("quiz_bot.db") as db:
        if cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, f"✅ ምዝገባዎ ተቀባይነት አግኝቷል። አሁን መወዳደር ይችላሉ!\n{ADMIN_USERNAME}")
            except: pass
            await msg.reply_text(f"Approved ID: {target_id} ✅")

        elif cmd == "anapprove" and target_id:
            await db.execute("DELETE FROM users WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "❌ የምዝገባ ጥያቄዎ ውድቅ ሆኗል። እባክዎ ደግመው ይሞክሩ።")
            except: pass
            await msg.reply_text("Rejected ❌")

        elif cmd == "block" and target_id:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME}")
            except: pass
            await msg.reply_text("Blocked 🚫")

        elif cmd == "unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል።")
            except: pass
            await msg.reply_text("Unblocked ✅")

        elif cmd == "unmute2" and target_id:
            await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?", (target_id,))
            await db.commit()
            # ስም ለማግኘት
            async with db.execute("SELECT username FROM users WHERE user_id=?", (target_id,)) as c: r = await c.fetchone()
            name = r[0] if r else "ተማሪ"
            await msg.reply_text(f"ተማሪ {name} እገዳዎ በአድሚኑ ትዕዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ።")
            try: await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል፤ በድጋሚ ላለመሳሳት ይሞክሩ።")
            except: pass

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await broadcast(context, "⛔️ ቦቱ ከአድሚን በመጣ ትዕዛዝ ቆሟል። ለበለጠ መረጃ @penguiner ን ያነጋግሩ።")
            await msg.reply_text("All Bots Stopped 🛑")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await broadcast(context, "✅ ቦቱ ተመልሷል። አሁን መጠቀም ትችላላችሁ።")
            await msg.reply_text("All Bots Resumed ✅")

        elif cmd == "log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 100") as c:
                res = "📜 Logs (Last 100):\n"
                for r in await c.fetchall(): res += f"{r[2]} {r[3]} | {r[0]} {r[1]}\n"
            await msg.reply_text(res or "No logs found.")

        elif cmd == "clear_log":
            await db.execute("DELETE FROM logs")
            await db.commit()
            await msg.reply_text("Logs Cleared 🧹")

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username FROM users") as c:
                res = "👥 ተመዝጋቢዎች:\n"
                users = await c.fetchall()
                for r in users: res += f"ID: <code>{r[0]}</code> | {r[1]}\n"
                res += f"\nጠቅላላ: {len(users)}"
            await msg.reply_text(res, parse_mode="HTML")

        elif cmd == "info" and target_id:
            async with db.execute("SELECT * FROM users WHERE user_id=?", (target_id,)) as c:
                u = await c.fetchone()
                if u:
                    txt = (f"ℹ️ User Info:\nName: {u[1]}\nID: <code>{u[0]}</code>\nPoints: {u[2]}\n"
                           f"Status: {u[3]}\nBlocked: {'Yes' if u[4] else 'No'}\nRegistered: {u[6]}")
                    await msg.reply_text(txt, parse_mode="HTML")

        elif cmd == "keep":
            async with db.execute("SELECT chat_id, chat_title, starter_name, start_time, subject FROM active_paths") as c:
                res = "📡 Active Paths:\n"
                for r in await c.fetchall():
                    res += f"📍 {r[1]} (ID: <code>{r[0]}</code>)\nStarted by: {r[2]}\nTime: {r[3]}\nSub: {r[4]}\n\n"
            await msg.reply_text(res or "No active paths.", parse_mode="HTML")

        elif cmd == "hmute":
            async with db.execute("SELECT user_id, username, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 Blocked/Muted List:\n"
                for r in await c.fetchall():
                    status = "Blocked" if r[2] else "Muted"
                    res += f"ID: <code>{r[0]}</code> | {r[1]} | {status}\n"
            await msg.reply_text(res or "No blocked/muted users.", parse_mode="HTML")

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points = 0")
            await db.commit()
            await msg.reply_text("Ranking Reset Done 🏆🧹")

        elif cmd == "close" and target_id:
            for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?", (target_id,))
            await db.commit()
            await msg.reply_text(f"Closed quiz for ID: {target_id}")

# ===================== NOTIFICATIONS =====================
async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    chat = update.effective_chat
    user = update.effective_user
    status = "✅ ቦቱ አብርቷል" if m.new_chat_member.status in ["member", "administrator"] else "❌ ቦቱ አጥፍቷል"
    for a in ADMIN_IDS:
        await context.bot.send_message(a, f"{status}\nቦታ: {chat.title or 'Private'}\nበ: {user.first_name} (ID: {user.id})")

# ===================== MAIN =====================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    keep_alive()
    
    app_bot = Application.builder().token(TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2","rank2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve","anapprove","block","unblock","unmute2","log","clear_log","oppt","opptt","pin","keep","hmute","info","clear_rank2","close"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    
    print("Bot is running...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
