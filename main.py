import os, json, asyncio, random, re, aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, MessageHandler, ChatMemberHandler, filters
)

# ===================== 24/7 HOSTING =====================
app = Flask('')
@app.route('/')
def home(): return "Strict Quiz Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== CONFIG =====================
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== DATABASE SETUP (65 RULES CORE) =====================
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        # Users Table: ሁሉንም Status (Pending/Approved/Blocked/Muted) ለመያዝ
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, 
            points REAL DEFAULT 0, status TEXT DEFAULT 'pending', 
            is_blocked INTEGER DEFAULT 0, muted_until TEXT, reg_at TEXT)""")
        
        # Polls Table: ለነጥብ አሰጣጥ (First winner logic)
        await db.execute("""CREATE TABLE IF NOT EXISTS active_polls(
            poll_id TEXT PRIMARY KEY, correct_option INTEGER, 
            chat_id INTEGER, first_winner INTEGER DEFAULT 0)""")
        
        # Logs Table: ለ /log ትዕዛዝ
        await db.execute("CREATE TABLE IF NOT EXISTS logs(user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)")
        
        # Paths Table: ለ /keep እና /keep2 ትዕዛዞች
        await db.execute("CREATE TABLE IF NOT EXISTS active_paths(chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT)")
        await db.commit()

# ===================== CORE LOGIC: POINT SYSTEM & QUIZ =====================
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    try:
        with open('questions.json', 'r', encoding='utf-8') as f: all_q = json.load(f)
        sub = job.data.get('subject')
        qs = [q for q in all_q if q.get('subject','').lower()==sub] if sub else all_q
        if not qs: return
        q = random.choice(qs)
        msg = await context.bot.send_poll(job.chat_id, f"📚 [{q.get('subject','General')}] {q['q']}", q['o'], 
            is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp',''))
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES(?,?,?,0)", (msg.poll.id, int(q['c']), job.chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?",(ans.user.id,)) as c: u = await c.fetchone()
        if not u or u[4]!="approved" or u[5]==1: return
        # Mute logic check
        if u[6] and datetime.now(timezone.utc) < datetime.fromisoformat(u[6]): return

        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c: p = await c.fetchone()
        if not p: return

        is_cor = (ans.option_ids[0]==p[0])
        # Rule 28 & 38: Points (8, 4, -1.5)
        pts = 8 if (is_cor and p[1]==0) else (4 if is_cor else -1.5)

        if is_cor and p[1]==0:
            await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ መልሶ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
        
        await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (ans.user.id, ans.user.first_name, "✔️" if is_cor else "❎", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# ===================== THE 65 RULES HANDLER =====================
async def handle_everything(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat = update.effective_user, update.effective_chat
    if not update.message or not update.message.text: return
    msg_text = update.message.text
    cmd = msg_text.split('@')[0].split()[0].lower()

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?",(user.id,)) as c: u = await c.fetchone()

        # --- REGISTRATION BLOCK ---
        if not u:
            await db.execute("INSERT INTO users(user_id,username,name,reg_at) VALUES(?,?,?,?)", 
                (user.id, f"@{user.username}" if user.username else "NoUser", user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
            await db.commit()
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው adminu እስኪቀበልዎ እባክዎ በትእግስት ይጠብቁ")
            for a in ADMIN_IDS: await context.bot.send_message(a, f"🆕 <b>/gof (New Request)</b>\nስም: {user.first_name}\nID: <code>{user.id}</code>")
            return
        
        if u[4]=="pending" and user.id not in ADMIN_IDS:
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} adminu ለጊዜው busy ነው ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን")
            return
        
        if u[5]==1 and user.id not in ADMIN_IDS:
            await update.message.reply_text(f"ከadmin በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል {ADMIN_USERNAME} ን ያናግሩ")
            return

        # --- RULES & PENALTIES (3.17 & 17 MINS) ---
        priv_allowed = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2","/rank2","/stop2"]
        group_allowed = ["/start2","/stop2"]

        if cmd.startswith("/"):
            # Private Violation
            if chat.type == "private" and cmd not in priv_allowed and user.id not in ADMIN_IDS:
                await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(user.id,)); await db.commit()
                await update.message.reply_text(f"የህግ ጥሰት... በቀጥታ ታግደዋል። {ADMIN_USERNAME} ን ያናግሩ።")
                for a in ADMIN_IDS: await context.bot.send_message(a, f"🚫 <b>Block Alert</b>\nID: <code>{user.id}</code>\nትዕዛዝ: {cmd}")
                return
            # Group Violation
            if chat.type != "private" and cmd not in group_allowed and user.id not in ADMIN_IDS:
                mute_to = (datetime.now(timezone.utc)+timedelta(minutes=17)).isoformat()
                await db.execute("UPDATE users SET points=points-3.17, muted_until=? WHERE user_id=?", (mute_to,user.id)); await db.commit()
                await update.message.reply_text(f"⚠️ {user.first_name} የታዘዘው ትዕዛዝ ከህግ ውጭ ስለሆነ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደዋል።", reply_to_message_id=update.message.message_id)
                return

        # --- USER COMMANDS ---
        if cmd in priv_allowed:
            if cmd == "/rank2":
                async with db.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT 20") as c:
                    res = "📊 <b>ደረጃ እና ነጥብ</b>\n"
                    for i,r in enumerate(await c.fetchall(),1): res+=f"{i}. {r[0]} - {r[1]} pts\n"
                    await update.message.reply_text(res, parse_mode="HTML")
                return

            if cmd == "/stop2":
                jobs = context.job_queue.get_jobs_by_name(str(chat.id))
                for j in jobs: j.schedule_removal()
                await db.execute("DELETE FROM active_paths WHERE chat_id=?",(chat.id,)); await db.commit()
                await update.message.reply_text("🏁 ውድድሩ ቆሟል።")
                return

            # Start Quiz
            if GLOBAL_STOP and user.id not in ADMIN_IDS:
                await update.message.reply_text(f"ከ admin በመጣ ትእዛዝ ቦቱ ቆሟል {ADMIN_USERNAME}")
                return
            sub = {"/history_srm2":"history","/geography_srm2":"geography","/mathematics_srm2":"mathematics","/english_srm2":"english"}.get(cmd)
            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject':sub}, name=str(chat.id))
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, datetime.now().strftime("%H:%M")))
            await db.commit()
            await update.message.reply_text("📢 ውድድሩ መጀመሩን እናሳውቃለን!")

# ===================== ADMIN POWER COMMANDS (ALL 65 RULES) =====================
async def admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    text = update.message.text.split()
    cmd = text[0][1:].lower()
    target_id = None

    # Rule 64: Reply ID Extraction
    if update.message.reply_to_message:
        rt = update.message.reply_to_message.text or ""
        m = re.search(r"ID:\s*(\d+)", rt)
        target_id = int(m.group(1)) if m else update.message.reply_to_message.from_user.id
    elif len(text) > 1: target_id = int(text[1])

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ ምዝገባዎ ተቀባይነት አግኝቷል")
        
        elif cmd == "block" and target_id:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(target_id,))
            await update.message.reply_text(f"ID {target_id} ታግዷል")
        
        elif cmd == "unmute2" and target_id:
            await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል")
            await update.message.reply_text("እገዳ ተነስቷል")

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await update.message.reply_text("🛑 ቦቱ ለሁሉም ቆሟል")

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await update.message.reply_text("✅ ቦቱ ስራ ጀምሯል")

        elif cmd == "log":
            async with db.execute("SELECT name, action, timestamp FROM logs ORDER BY rowid DESC LIMIT 30") as c:
                res = "📜 <b>Logs:</b>\n" + "\n".join([f"{r[0]} | {r[1]} | {r[2]}" for r in await c.fetchall()])
                await update.message.reply_text(res or "ባዶ ነው", parse_mode="HTML")

        elif cmd == "hmute":
            async with db.execute("SELECT user_id, name, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 <b>Blocked/Muted:</b>\n"
                for r in await c.fetchall():
                    s = "Block" if r[2]==1 else "Mute"
                    res += f"{r[1]} (<code>{r[0]}</code>) - {s}\n"
                await update.message.reply_text(res or "የለም", parse_mode="HTML")

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points=0"); await update.message.reply_text("Rank Cleared")

        await db.commit()

# ===================== STARTUP & SHUTDOWN =====================
async def status_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    st = "✅ አብርቷል" if m.new_chat_member.status=="member" else "❌ አጥፍቷል"
    for a in ADMIN_IDS: await context.bot.send_message(a, f"ተማሪ {u.first_name} ቦቱን {st}\nID: {u.id}")

def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    
    # አንድ ወጥ የሆነ Handler ለሁሉም 65 ህጎች
    app_bot.add_handler(MessageHandler(filters.COMMAND & filters.ChatType.PRIVATE, handle_everything))
    app_bot.add_handler(MessageHandler(filters.COMMAND & ~filters.ChatType.PRIVATE, handle_everything))
    
    # አድሚን ብቻ
    admin_cmds = ["approve","anapprove","block","unblock","unmute2","log","clear_log","oppt","opptt","hmute","pin","clear_rank2","close","keep","keep2","info"]
    app_bot.add_handler(CommandHandler(admin_cmds, admin_dispatch))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_change, ChatMemberHandler.MY_CHAT_MEMBER))
    
    keep_alive()
    app_bot.run_polling()

if __name__=="__main__": main()
