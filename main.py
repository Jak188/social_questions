import os, json, asyncio, random, re, aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, MessageHandler, ChatMemberHandler, filters
)

# ===================== FLASK (24/7) =====================
app = Flask('')
@app.route('/')
def home(): return "Strict System Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== CONFIG =====================
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== DB INIT (Rule 7, 18, 45, 53) =====================
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, 
            points REAL DEFAULT 0, status TEXT DEFAULT 'pending', 
            is_blocked INTEGER DEFAULT 0, muted_until TEXT, reg_at TEXT)""")
        await db.execute("CREATE TABLE IF NOT EXISTS active_polls(poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS logs(user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS active_paths(chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT)")
        await db.commit()

# ===================== UTILS (Rule 9, 31, 37, 60, 61, 65) =====================
async def admin_notify(context, text):
    for a in ADMIN_IDS:
        try: await context.bot.send_message(a, f"{text}\n{ADMIN_USERNAME}", parse_mode="HTML")
        except: pass

async def broadcast(context, text):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT user_id FROM users WHERE is_blocked=0") as c: us = await c.fetchall()
        async with db.execute("SELECT chat_id FROM active_paths") as c: gr = await c.fetchall()
    ids = {u[0] for u in us} | {g[0] for g in gr}
    for cid in ids:
        try: await context.bot.send_message(cid, f"{text}\nለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ", parse_mode="HTML")
        except: pass

# ===================== QUIZ ENGINE (Rule 25, 27, 28, 38, 39) =====================
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
        if u[6] and datetime.now(timezone.utc) < datetime.fromisoformat(u[6]): return

        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c: p = await c.fetchone()
        if not p: return

        is_cor = (ans.option_ids[0]==p[0])
        # Rule 28 & 38: Points logic
        pts = 8 if (is_cor and p[1]==0) else (4 if is_cor else -1.5)

        if is_cor and p[1]==0:
            await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ መልሶ 8 ነጥብ አግኝቷል!")

        await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (ans.user.id, ans.user.first_name, "✔️" if is_cor else "❎", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# ===================== MAIN HANDLERS (Rule 1, 2, 3, 4, 5, 29, 30, 35, 41, 62, 63) =====================
async def handle_user_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat = update.effective_user, update.effective_chat
    if not update.message or not update.message.text: return
    cmd = update.message.text.split('@')[0].split()[0].lower()

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?",(user.id,)) as c: u = await c.fetchone()

        # Registration (Rule 1, 5, 41, 55, 61)
        if not u:
            await db.execute("INSERT INTO users(user_id,username,name,reg_at) VALUES(?,?,?,?)", 
                (user.id, f"@{user.username}" if user.username else "NoUser", user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
            await db.commit()
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው adminu እስኪቀበልዎ እባክዎ በትእግስት ይጠብቁ")
            await admin_notify(context, f"🆕 <b>/gof (New Request)</b>\nስም: {user.first_name}\nID: <code>{user.id}</code>\nUsername: {user.username}")
            return
        
        if u[4]=="pending":
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} adminu ለጊዜው busy ነው ጥያቄዎ ተቀባይነት ሲያገኝ የምናሳውቅዎ ይሆናል እናመሰግናለን")
            return
        
        if u[5]==1: # Rule 3 & 19
            await update.message.reply_text(f"ከadmin በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
            return

        # Violation Checks (Rule 29, 30, 35, 62, 63)
        priv_allowed = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2","/rank2","/stop2"]
        group_allowed = ["/start2","/stop2"]

        if cmd.startswith("/"):
            if chat.type == "private" and cmd not in priv_allowed and user.id not in ADMIN_IDS:
                await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(user.id,)); await db.commit()
                await update.message.reply_text(f"የህግ ጥሰት... በቀጥታ ታግደዋል። {ADMIN_USERNAME} ን ያናግሩ።")
                await admin_notify(context, f"🚫 <b>Auto Block (Private)</b>\nተማሪ: {user.first_name}\nID: {user.id}\nምክንያት: ያልተፈቀደ ትእዛዝ {cmd}")
                return
            
            if chat.type != "private" and cmd not in group_allowed and user.id not in ADMIN_IDS:
                mute_to = (datetime.now(timezone.utc)+timedelta(minutes=17)).isoformat()
                await db.execute("UPDATE users SET points=points-3.17, muted_until=? WHERE user_id=?", (mute_to,user.id)); await db.commit()
                await update.message.reply_text(f"⚠️ {user.first_name} የታዘዘው ትዕዛዝ ከህግ ውጭ ስለሆነ 3.17 ነጥብ ተቀንሶ ለ 17 ደቂቃ ታግደዋል።", reply_to_message_id=update.message.message_id)
                await admin_notify(context, f"⚠️ <b>Group Mute Alert</b>\nተማሪ: {user.first_name}\nID: <code>{user.id}</code>\nGroup: {chat.title}\nለማንሳት Replay /unmute2 በል")
                return

        # Start Quiz (Rule 10-15, 25, 31, 37, 40)
        if cmd in ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2"]:
            if GLOBAL_STOP and user.id not in ADMIN_IDS:
                await update.message.reply_text(f"ከ admin በመጣ ትእዛዝ መሰረት ለጊዜው ቆሟል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
                return
            sub = {"/history_srm2":"history","/geography_srm2":"geography","/mathematics_srm2":"mathematics","/english_srm2":"english"}.get(cmd)
            await update.message.reply_text("📢 ውድድሩ መጀመሩን እናሳውቃለን!")
            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject':sub}, name=str(chat.id))
            now_t = datetime.now()
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, now_t.strftime("%Y-%m-%d %H:%M")))
            await db.commit()
            await admin_notify(context, f"🚀 <b>ውድድር ተጀመረ</b>\nበ: {user.first_name}\nቦታ: {chat.title or 'Private'}\nሰዓት: {now_t.strftime('%H:%M')}")

        elif cmd=="/stop2": # Rule 15 & 42
            jobs = context.job_queue.get_jobs_by_name(str(chat.id))
            if not jobs:
                if chat.type=="private": await update.message.reply_text("Eyetetekemubet slalhone legizew komual lemasjemer /start2 yibelu")
                return
            for j in jobs: j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?",(chat.id,))
            if chat.type=="private":
                await update.message.reply_text(f"🏁 ውድድሩ ቆሟል። ያገኙት ነጥብ: {u[3]}")
            else:
                async with db.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT 15") as c:
                    res = "📊 <b>Best 15 (ውድድሩ ተጠናቋል)</b>\n"
                    for i,r in enumerate(await c.fetchall(),1): res+=f"{i}. {r[0]} - {r[1]} pts\n"
                await update.message.reply_text(res, parse_mode="HTML")
            await db.commit()
            await admin_notify(context, f"🏁 <b>ውድድር ቆመ</b>\nቦታ: {chat.title or 'Private'}")

# ===================== ADMIN CONTROLS (Rule 16-24, 32-36, 43-59, 64) =====================
async def admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    text = update.message.text.split()
    cmd = text[0][1:].lower()
    target_id = None

    # Rule 64: Smart Extraction from Reply
    if update.message.reply_to_message:
        rt = update.message.reply_to_message.text or ""
        m = re.search(r"ID:\s*(\d+)", rt)
        target_id = int(m.group(1)) if m else update.message.reply_to_message.from_user.id
    elif len(text) > 1:
        try: target_id = int(text[1])
        except: pass

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve" and target_id: # Rule 24, 56
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ ምዝገባዎ ተቀባይነት አግኝቷል")
            await update.message.reply_text("Approved ✅")
        
        elif cmd == "anapprove" and target_id: # Rule 6, 24, 57
            await db.execute("DELETE FROM users WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "ጥያቄዎ ተቀባይነት አላገኘም እባክዎ እንደገና ይሞክሩ")
            await update.message.reply_text("Rejected ❌")

        elif cmd == "block" and target_id: # Rule 19, 47
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(target_id,))
            await update.message.reply_text(f"Blocked 🚫")

        elif cmd == "unblock" and target_id: # Rule 23, 49
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ [እገዳዎ ተነስቷል]")
            await update.message.reply_text("Unblocked ✅")

        elif cmd == "unmute2" and target_id: # Rule 30, 35, 51
            await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?",(target_id,))
            async with db.execute("SELECT name FROM users WHERE user_id=?",(target_id,)) as c: r = await c.fetchone()
            name = r[0] if r else "ተማሪ"
            await update.message.reply_text(f"ተማሪ {name} እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ")
            await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል")

        elif cmd == "oppt": # Rule 21, 58, 61
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await broadcast(context, "ከ admin በመጣ ትእዛዝ መሰረት ለታወቀ ዝግጅት ቦቱ ተቆጥቧል")

        elif cmd == "opptt": # Rule 22, 59
            GLOBAL_STOP = False
            await broadcast(context, "✅ ቦቱ ተመልሷል ስራ ጀምሯል")

        elif cmd == "log": # Rule 24, 32, 52
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 50") as c:
                res = "📜 <b>Log History</b>\n"
                for r in await c.fetchall(): res += f"{r[0]} | {r[1]} | {r[2]} {r[3]}\n"
                await update.message.reply_text(res or "Log Empty", parse_mode="HTML")

        elif cmd == "hmute": # Rule 33, 47
            async with db.execute("SELECT user_id, username, name, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 <b>Blocked/Muted List</b>\n"
                for r in await c.fetchall():
                    st = "blocked 🚫" if r[3]==1 else "muted 🔇"
                    res += f"{r[2]} (@{r[1]}) ID: <code>{r[0] house}</code> -> {st}\n"
                await update.message.reply_text(res or "No one blocked", parse_mode="HTML")

        elif cmd == "info" and target_id: # Rule 34
            async with db.execute("SELECT * FROM users WHERE user_id=?",(target_id,)) as c:
                u = await c.fetchone()
                if u: await update.message.reply_text(f"👤 Name: {u[2]}\nID: <code>{u[0]}</code>\nUser: @{u[1]}\nPoints: {u[3]}\nReg: {u[7]}", parse_mode="HTML")

        elif cmd == "pin" or cmd == "status": # Rule 16, 54
            async with db.execute("SELECT COUNT(*) FROM users") as c: count = (await c.fetchone())[0]
            async with db.execute("SELECT name, username, user_id FROM users") as c:
                ulist = "\n".join([f"{r[0]} (@{r[1]}) - <code>{r[2]}</code>" for r in await c.fetchall()])
                await update.message.reply_text(f"👥 Total: {count}\n\n{ulist}", parse_mode="HTML")

        elif cmd in ["keep", "keep2"]: # Rule 20, 36, 43
            async with db.execute("SELECT * FROM active_paths") as c:
                res = "🔍 <b>Active Sessions:</b>\n"
                for r in await c.fetchall(): res += f"📍 {r[1]} | 👤 {r[2]} | ⏰ {r[3]}\n"
                await update.message.reply_text(res or "No active sessions")

        elif cmd == "close" and target_id: # Rule 23, 46
            for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?",(target_id,))
            await update.message.reply_text(f"Closed session for {target_id}")

        elif cmd == "clear_rank2": # Rule 18, 45
            await db.execute("UPDATE users SET points=0"); await update.message.reply_text("Rank Cleared")

        elif cmd == "clear_log": # Rule 53
            await db.execute("DELETE FROM logs"); await update.message.reply_text("Log Cleared")

        await db.commit()

# ===================== MEMBER STATUS (Rule 9, 60, 61) =====================
async def status_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    u = update.effective_user
    status = "✅ አብርቷል" if m.new_chat_member.status == "member" else "❌ አጥፍቷል"
    await admin_notify(context, f"ተማሪ <b>{u.first_name}</b> ቦቱን {status}!\nID: {u.id}")

# ===================== MAIN =====================
def main():
    asyncio.get_event_loop().run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()

    # Dynamic Rules Engine
    app_bot.add_handler(MessageHandler(filters.COMMAND & filters.ChatType.PRIVATE, handle_user_actions))
    app_bot.add_handler(MessageHandler(filters.COMMAND & ~filters.ChatType.PRIVATE, handle_user_actions))
    
    # Admin Panel
    admin_cmds = ["approve","anapprove","block","unblock","unmute2","log","clear_log","oppt","opptt","hmute","pin","clear_rank2","close","keep","keep2","info","status"]
    app_bot.add_handler(CommandHandler(admin_cmds, admin_dispatch))
    
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_change, ChatMemberHandler.MY_CHAT_MEMBER))
    
    keep_alive()
    print("Strict Bot is running...")
    app_bot.run_polling()

if __name__=="__main__": main()
