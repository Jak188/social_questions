PK:
# ===================== IMPORTS =====================
import os, json, asyncio, random, re
import aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread

from telegram import Update, Poll
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, MessageHandler, ChatMemberHandler, filters
)

# ===================== FLASK (Keep-Alive) =====================
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"

def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== CONFIG =====================
TOKEN = "PUT_YOUR_TOKEN_HERE"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== DB INIT =====================
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            points REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            is_blocked INTEGER DEFAULT 0,
            muted_until TEXT,
            reg_at TEXT
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS active_polls(
            poll_id TEXT PRIMARY KEY,
            correct_option INTEGER,
            chat_id INTEGER,
            first_winner INTEGER DEFAULT 0
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS logs(
            user_id INTEGER, name TEXT, action TEXT, 
            timestamp TEXT, date TEXT
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS active_paths(
            chat_id INTEGER PRIMARY KEY,
            chat_title TEXT,
            starter_name TEXT,
            start_time TEXT
        )""")
        await db.commit()

# ===================== UTIL (Broadcasting) =====================
async def broadcast_message(context, text):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT user_id FROM users") as c:
            users = await c.fetchall()
        async with db.execute("SELECT chat_id FROM active_paths") as c:
            groups = await c.fetchall()
    ids = {u[0] for u in users} | {g[0] for g in groups}
    for cid in ids:
        try:
            await context.bot.send_message(cid, text, parse_mode="HTML")
            await asyncio.sleep(0.05)
        except: pass

# ===================== QUIZ LOGIC =====================
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
        sub = job.data.get('subject')
        questions = [q for q in all_q if q.get('subject','').lower()==sub] if sub else all_q
        if not questions: return

        q = random.choice(questions)
        msg = await context.bot.send_poll(
            job.chat_id, f"📚 [{q.get('subject','General')}] {q['q']}",
            q['o'], is_anonymous=False, type=Poll.QUIZ,
            correct_option_id=int(q['c']), explanation=q.get('exp','')
        )
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO active_polls VALUES(?,?,?,0)", (msg.poll.id, int(q['c']), job.chat_id))
            await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    async with aiosqlite.connect('quiz_bot.db') as db:
        # Logs everyone (registered or not)
        now = datetime.now()
        async with db.execute("SELECT correct_option, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c:

p = await c.fetchone()
        
        if p:
            is_correct = (ans.option_ids[0]==p[0])
            await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (ans.user.id, ans.user.first_name, "✓" if is_correct else "✗", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
            await db.commit()

        # Points only for approved users
        async with db.execute("SELECT * FROM users WHERE user_id=?",(ans.user.id,)) as c:
            u = await c.fetchone()
        if not u or u[3]!="approved" or u[4]==1: return
        if u[5] and datetime.now(timezone.utc) < datetime.fromisoformat(u[5]): return

        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c:
            p = await c.fetchone()
        
        is_correct = (ans.option_ids[0]==p[0])
        points = 8 if (is_correct and p[1]==0) else (4 if is_correct else 1.5)

        if is_correct and p[1]==0:
            await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ መልሶ 8 ነጥብ አግኝቷል!", parse_mode="HTML")

        await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (points, ans.user.id))
        await db.commit()

# ===================== START & SECURITY =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not update.message: return
    cmd = update.message.text.split('@')[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ከአድሚን ትእዛዝ መሠረት ቦቱ ለጊዜው ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?",(user.id,)) as c:
            u = await c.fetchone()

        if not u:
            await db.execute("INSERT INTO users(user_id,username,reg_at) VALUES(?,?,?)", (user.id, user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            await db.commit()
            await update.message.reply_text(f"👋 ውድ ተማሪ {user.first_name}\nየምዝገባ ጥያቄዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ በትእግስት ይጠብቁ።")
            for a in ADMIN_IDS: await context.bot.send_message(a, f"👤 New registration\nName:{user.first_name}\nID:{user.id}")
            return

        if u[3]=="pending":
            await update.message.reply_text(f"⏳ ውድ ተማሪ {user.first_name}\nአድሚኑ ለጊዜው busy ነው። ተቀባይነት ሲያገኝ እናሳውቃለን።")
            return

        if u[4]==1:
            await update.message.reply_text(f"🚫 ውድ ተማሪ {user.first_name} በአድሚን ትእዛዝ መሠረት ለጊዜው እንዳይጠቀሙ ታግደዋል። መፍትሄ ለማግኘት {ADMIN_USERNAME} ን ያነጋግሩ።")
            return

        allowed_priv = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2","/rank2","/stop2"]
        if chat.type=="private" and cmd.startswith("/") and cmd not in allowed_priv and user.id not in ADMIN_IDS:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(user.id,))
            await db.commit()
            await update.message.reply_text(f"⚠️ የህግ ጥሰት። ታግደዋል። {ADMIN_USERNAME}")
            return

        if chat.type!="private" and cmd.startswith("/") and cmd not in ["/start2","/stop2"] and user.id not in ADMIN_IDS:
            mute_to = (datetime.now(timezone.utc)+timedelta(minutes=17)).isoformat()
            await db.execute("UPDATE users SET points=points-3.17, muted_until=? WHERE user_id=?", (mute_to,user.id))
            await db.commit()
            await update.message.reply_text(f"⚠️ {user.first_name} 3.17 ነጥብ ተቀንሷል፣ ለ 17 ደቂቃ ታግደዋል።")
            return

        if cmd in allowed_priv or cmd=="/start2":

if cmd == "/stop2":
                for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
                await db.execute("DELETE FROM active_paths WHERE chat_id=?",(chat.id,))
                await db.commit()
                await update.message.reply_text("🛑 ውድድሩ ቆሟል።")
                return

            sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
            await update.message.reply_text("📢 ውድድር ጀመረ!")
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
            await db.commit()
            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject':sub}, name=str(chat.id))

# ===================== ADMIN CONTROLS =====================
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    target_id = None
    target_name = "ተማሪ"

    if update.message.reply_to_message:
        r_text = update.message.reply_to_message.text
        match_id = re.search(r"ID:(\d+)", r_text)
        match_name = re.search(r"Name:(.*?)\n", r_text) or re.search(r"\| (.*?)\n", r_text)
        if match_id: target_id = int(match_id.group(1))
        if match_name: target_name = match_name.group(1).strip()
    elif len(txt)>1:
        try: target_id = int(txt[1])
        except: pass

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd=="approve" and target_id:
            await db.execute("UPDATE users SET status='approved' WHERE user_id=?",(target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id,"✅ ምዝገባዎ ተቀባይነት አግኝቷል")
            except: pass
            await update.message.reply_text("Approved")
        
        elif cmd=="block" and target_id:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?",(target_id,))
            await db.commit()
            try:
                # Check if it's a group or user (simplified)
                await context.bot.send_message(target_id, f"ወድ ተማሪ {target_name} በአድሚን ትእዛዝ መሠረት ለጊዜው እንዳይጠቀሙ ታግደዋል መፍትሄ ለማግኘት {ADMIN_USERNAME} ን ያነጋግሩ")
            except:
                await update.message.reply_text(f"ውድ የዚህ group አባላት በሙሉ ይህ group የ privacy ጥሰት ስላደረሰ ለጊዜው ቦቱ እዚህ group ላይ እንዳይሰራ ታግዷል\nOWNER OF THIS BOT {ADMIN_USERNAME}")
            await update.message.reply_text("Blocked")

        elif cmd=="unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?",(target_id,))
            await db.commit()
            try:
                await context.bot.send_message(target_id, f"ውድ ተማሪ {target_name} የነበረብዎ ችግር ስለተፈታ አሁን መጠቀም ይችላሉ\n{ADMIN_USERNAME}")
            except:
                await update.message.reply_text("ይህ group የነበረበት ችግር ስለተፈታ አሁን መጠቀም ይችላሉ")
            await update.message.reply_text("Unblocked")

        elif cmd=="close" and target_id:
            for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id=?",(target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "ቦቱን እየተጠቀሙበት ስላልሆነ አድሚኑ አስቁሟል ለመጀመር /start2 ይበሉ")
            except: pass
            await update.message.reply_text("Closed")

        elif cmd=="oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            await broadcast_message(context, f"⛔️ ቦቱ ከአድሚን ትእዛዝ መሠረት ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")

        elif cmd=="opptt":
            GLOBAL_STOP = False
            await broadcast_message(context, "✅ ቦቱ ተመልሷል")

elif cmd=="log":
            async with db.execute("SELECT name,action,date,timestamp FROM logs ORDER BY rowid DESC LIMIT 230") as c:
                res="📜 Logs (Top 230)\n"
                for r in await c.fetchall(): res+=f"{r[0]} {r[1]} {r[2]} {r[3]}\n"
            await update.message.reply_text(res)
            
        # Other admin commands (unmute, rank2, info, etc.) stay exactly as before
        elif cmd=="rank2":
            async with db.execute("SELECT username,points FROM users ORDER BY points DESC LIMIT 15") as c:
                res="📊 Rank\n"
                for i,r in enumerate(await c.fetchall(),1): res+=f"{i}. {r[0]} - {r[1]} pts\n"
            await update.message.reply_text(res)

# ===================== MAIN =====================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2","rank2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve","anapprove","block","unblock","unmute","unmute2","rank2","clear_rank2","pin","keep","keep2","log","clear_log","oppt","opptt","close","hmute","gof","info"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if name=="main":
    main()
