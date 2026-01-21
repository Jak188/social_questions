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
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== CONFIG =====================
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== DB INIT =====================
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, 
            points REAL DEFAULT 0, status TEXT DEFAULT 'pending', 
            is_blocked INTEGER DEFAULT 0, muted_until TEXT, reg_at TEXT)""")
        await db.execute("CREATE TABLE IF NOT EXISTS active_polls(poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS logs(user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS active_paths(chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT, type TEXT)")
        await db.commit()

# ===================== UTILS =====================
async def admin_notify(context, text):
    for a in ADMIN_IDS:
        try: await context.bot.send_message(a, text, parse_mode="HTML")
        except: pass

async def broadcast(context, text):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT user_id FROM users") as c: us = await c.fetchall()
        async with db.execute("SELECT chat_id FROM active_paths") as c: gr = await c.fetchall()
    ids = {u[0] for u in us} | {g[0] for g in gr}
    for cid in ids:
        try: await context.bot.send_message(cid, text, parse_mode="HTML")
        except: pass

# ===================== QUIZ ENGINE =====================
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
        pts = 8 if (is_cor and p[1]==0) else (4 if is_cor else 1.5)
        if is_cor and p[1]==0:
            await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ መልሶ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
        await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (pts, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (ans.user.id, ans.user.first_name, "✔️" if is_cor else "❎", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# ===================== HANDLERS =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat = update.effective_user, update.effective_chat
    if not update.message: return
    cmd = update.message.text.split('@')[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ከጥበቃ ትእዛዝ መሠረት ለጊዜው ቦቱ ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
        return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?",(user.id,)) as c: u = await c.fetchone()
        
        # 1. Registration Logic
        if not u:
            await db.execute("INSERT INTO users(user_id,username,name,reg_at) VALUES(?,?,?,?)", 
                (user.id, f"@{user.username}" if user.username else "NoUser", user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            await db.commit()
            await update.message.reply_text(f"👋 ውድ ተማሪ {user.first_name}\nየምዝገባ ጥያቄዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ በትእግስት ይጠብቁ።")
            await admin_notify(context, f"🆕 <b>የምዝገባ ጥያቄ (Gof)</b>\nስም: {user.first_name}\nUser: @{user.username}\nID: <code>{user.id}</code>")
            return
        if u[4]=="pending":
            await update.message.reply_text(f"⏳ ውድ ተማሪ {user.first_name}\nአድሚኑ ለጊዜው busy ነው። ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቃለን።")
            return
        if u[5]==1:
            await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትእዛዝ መሠረት ለጊዜው ታግደዋል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
            return

        # 2. Security (Points 29, 30, 35)
        priv_allowed = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2","/rank2","/stop2"]
        if chat.type=="private" and cmd.startswith("/") and cmd not in priv_allowed and user.id not in ADMIN_IDS:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(user.id,)); await db.commit()
            await update.message.reply_text(f"⚠️ የህግ ጥሰት። በቀጥታ ታግደዋል። {ADMIN_USERNAME} ን ያናግሩ።")
            await admin_notify(context, f"🚫 <b>Auto Block (Private)</b>\nID: {user.id}\nምክንያት: ያልተፈቀደ ትእዛዝ")
            return
        if chat.type!="private" and cmd.startswith("/") and cmd not in ["/start2","/stop2"] and user.id not in ADMIN_IDS:
            mute_to = (datetime.now(timezone.utc)+timedelta(minutes=17)).isoformat()
            await db.execute("UPDATE users SET points=points-3.17, muted_until=? WHERE user_id=?", (mute_to,user.id)); await db.commit()
            await update.message.reply_text(f"⚠️ {user.first_name} 3.17 ነጥብ ተቀንሷል፣ ለ 17 ደቂቃ ታግደዋል።", reply_to_message_id=update.message.message_id)
            await admin_notify(context, f"⚠️ <b>User Muted in Group</b>\nID: <code>{user.id}</code>\nGroup: {chat.title}\nለመፍታት reply አድርገህ /unmute2 በል")
            return

        # 3. Competition Commands
        if cmd in ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2"]:
            sub = {"/history_srm2":"history","/geography_srm2":"geography","/mathematics_srm2":"mathematics","/english_srm2":"english"}.get(cmd)
            await update.message.reply_text("📢 ውድድር ጀመረ!\n8 ነጥብ (ቀድሞ) | 4 ነጥብ | 1.5 ነጥብ")
            now_t = datetime.now()
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, now_t.strftime("%Y-%m-%d %H:%M"), chat.type))
            await db.commit()
            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject':sub}, name=str(chat.id))
            await admin_notify(context, f"🚀 <b>ውድድር ተጀመረ</b>\nበ: {user.first_name} (<code>{user.id}</code>)\nቦታ: {chat.title or 'Private'}\nሰዓት: {now_t}")

        elif cmd=="/stop2":
            jobs = context.job_queue.get_jobs_by_name(str(chat.id))
            if not jobs: return
            for j in jobs: j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?",(chat.id,))
            if chat.type=="private":
                await update.message.reply_text(f"🏁 ውድድሩ ቆሟል። የእርስዎ ነጥብ: {u[3]}")
            else:
                async with db.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT 15") as c:
                    res = "📊 <b>Best 15</b>\n"
                    for i,r in enumerate(await c.fetchall(),1): res+=f"{i}. {r[0]} - {r[1]} pts\n"
                await update.message.reply_text(res, parse_mode="HTML")
            await db.commit()
            await admin_notify(context, f"🏁 <b>ውድድር ቆመ</b>\nቦታ: {chat.title or 'Private'}\nሰዓት: {datetime.now()}")

# ===================== ADMIN CONTROLS =====================
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    target_id = None
    
    if update.message.reply_to_message:
        m = re.search(r"ID:\s*(\d+)", update.message.reply_to_message.text or "")
        target_id = int(m.group(1)) if m else update.message.reply_to_message.from_user.id
    elif len(txt)>1:
        try: target_id = int(txt[1])
        except: pass

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd=="approve" and target_id:
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ ምዝገባዎ ተቀባይነት አግኝቷል")
            await update.message.reply_text("Approved")
        elif cmd=="anapprove" and target_id:
            await db.execute("DELETE FROM users WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "❌ ጥያቄዎ ተቀባይነት አላገኘም፣ እባክዎ እንደገና ይሞክሩ")
            await update.message.reply_text("Rejected")
        elif cmd=="block" and target_id:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(target_id,))
            await update.message.reply_text("Blocked")
        elif cmd=="unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል")
            await update.message.reply_text("Unblocked")
        elif cmd=="unmute2" and target_id:
            await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?",(target_id,))
            await context.bot.send_message(target_id, "✅ እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ")
            await update.message.reply_text("Unmuted")
        elif cmd=="rank2":
            async with db.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT 15") as c:
                res="📊 <b>Rank</b>\n"
                for i,r in enumerate(await c.fetchall(),1): res+=f"{i}. {r[0]} - {r[1]} pts\n"
            await update.message.reply_text(res, parse_mode="HTML")
        elif cmd=="clear_rank2":
            await db.execute("UPDATE users SET points=0"); await update.message.reply_text("Rank Cleared")
        elif cmd=="pin":
            async with db.execute("SELECT user_id, username, name FROM users") as c:
                res="👥 <b>Registered</b>\n"
                for r in await c.fetchall(): res+=f"ID: <code>{r[0]}</code> | {r[1]} ({r[2]})\n"
            await update.message.reply_text(res, parse_mode="HTML")
        elif cmd=="keep" or cmd=="keep2":
            async with db.execute("SELECT * FROM active_paths") as c:
                res="🔍 <b>Active Paths</b>\n"
                for r in await c.fetchall(): res+=f"{r[1]} | {r[2]} | {r[3]}\n"
            await update.message.reply_text(res or "No Active Paths", parse_mode="HTML")
        elif cmd=="oppt":
            global GLOBAL_STOP
            GLOBAL_STOP=True
            await broadcast(context, f"⛔️ ከ admin በመጣ ትእዛዝ መሠረት ቦቱ ለጊዜው ተገትቧል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
        elif cmd=="opptt":
            GLOBAL_STOP=False
            await broadcast(context, "✅ ቦቱ ተመልሷል")
        elif cmd=="close" and target_id:
            for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?",(target_id,))
            await update.message.reply_text("Closed")
        elif cmd=="log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 50") as c:
                res="📜 <b>Logs</b>\n"
                for r in await c.fetchall(): res+=f"{r[0]} {r[1]} {r[2]} {r[3]}\n"
            await update.message.reply_text(res or "Empty Logs", parse_mode="HTML")
        elif cmd=="info" and target_id:
            async with db.execute("SELECT * FROM users WHERE user_id=?",(target_id,)) as c:
                u = await c.fetchone()
                if u: await update.message.reply_text(f"👤 Name: {u[2]}\nUser: {u[1]}\nID: <code>{u[0]}</code>\nPoints: {u[3]}\nReg: {u[7]}", parse_mode="HTML")
        await db.commit()

# ===================== STATUS NOTIF =====================
async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    st = "✅ ቦቱ አብርቷል" if m.new_chat_member.status=="member" else "❌ ቦቱ አጥፍቷል"
    await admin_notify(context, f"{st}\nበ: {update.effective_user.first_name}\nID: {update.effective_user.id}")

# ===================== MAIN =====================
def main():
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve","anapprove","block","unblock","unmute","unmute2","rank2","clear_rank2","pin","keep","keep2","log","oppt","opptt","close","info"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive(); app_bot.run_polling()

if __name__=="__main__": main()
