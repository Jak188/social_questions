import os, json, asyncio, random, aiosqlite, re
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server (For 24/7 keeping alive) ---
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

# --- Utility Functions ---
async def get_all_chats():
    chats = set()
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT user_id FROM users") as c:
            for r in await c.fetchall(): chats.add(r[0])
        async with db.execute("SELECT chat_id FROM active_paths") as c:
            for r in await c.fetchall(): chats.add(r[0])
    return chats

async def broadcast_message(context, text):
    chat_ids = await get_all_chats()
    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=text, parse_mode='HTML')
            await asyncio.sleep(0.05)
        except: continue

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
            msg = await context.bot.send_poll(job.chat_id, f"📚 [{q.get('subject', 'General')}] {q['q']}", q['o'], 
                is_anonymous=False, type=Poll.QUIZ, correct_option_id=int(q['c']), explanation=q.get('exp', ''))
            async with aiosqlite.connect('quiz_bot.db') as db:
                await db.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (?, ?, ?)", (msg.poll.id, int(q['c']), job.chat_id))
                await db.commit()
    except: pass

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (ans.user.id,)) as c: user = await c.fetchone()
        if not user or user[3] != 'approved' or user[4] == 1: return
        if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return
        
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            p_data = await c.fetchone()
        if not p_data: return
        
        is_correct = (ans.option_ids[0] == p_data[0])
        points = 8 if (is_correct and p_data[1] == 0) else (4 if is_correct else 1.5)
        
        if is_correct and p_data[1] == 0:
            await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
            await context.bot.send_message(p_data[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!", parse_mode='HTML')
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES (?, ?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# --- Core Logic & Security ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not update.message or not update.message.text: return
    cmd = update.message.text.split('@')[0].lower()

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ከአድሚን በመጣ ትዕዛዝ መሰረት ቦቱ ለጊዜው ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።", parse_mode='HTML')
        return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)) as c: u_data = await c.fetchone()

        # 1. Registration Logic
        if not u_data:
            reg_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, reg_at))
            await db.commit()
            await update.message.reply_text(f"👋 ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው ጥያቄውን አድሚኑ እስኪቀበልዎ እባክዎ በትእግስት ይጠብቁ።", parse_mode='HTML')
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 <b>አዲስ ምዝገባ:</b>\nስም: {user.first_name}\nID: <code>{user.id}</code>", parse_mode='HTML')
            return

        if u_data[3] == 'pending':
            await update.message.reply_text(f"⏳ ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው ቢዚ ነው ጥያቄዎ ተቀባይነት ሲያገኝ የምናሳውቅዎ ይሆናል እናመሰግናለን።", parse_mode='HTML')
            return

        if u_data[4] == 1:
            await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።", parse_mode='HTML')
            return

        # 2. Security Rules (Point 29, 30, 35)
        if user.id not in ADMIN_IDS:
            allowed_priv = ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/stop2", "/keep2"]
            if chat.type == "private" and cmd not in allowed_priv:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
                await update.message.reply_text(f"⚠️ የህግ ጥሰት፡ ከተፈቀደልዎ ትእዛዝ ውጭ አዘዋል። በዚሁ ምክንያት ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።", parse_mode='HTML')
                for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🚫 ተማሪ {user.first_name} (ID: {user.id}) በግል የተከለከለ ትዕዛዝ በመጠቀሙ ታግዷል።")
                return
            elif chat.type != "private" and cmd.startswith('/') and cmd not in ["/start2", "/stop2"]:
                mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
                await db.commit()
                await update.message.reply_text(f"⚠️ የህግ ጥሰት.. {user.first_name} የአድሚን ትእዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል ለ17 ደቂቃ ታግደሃል።", parse_mode='HTML')
                for adm in ADMIN_IDS: await context.bot.send_message(adm, f"⚠️ ተማሪ {user.first_name} (ID: {user.id}) ከግሩፕ <b>{chat.title}</b> ታግዷል። እገዳውን ለማንሳት reply አድርገህ <code>/unmute2</code> በል", parse_mode='HTML')
                return

        # 3. Competition Start (Point 10-14, 31, 37, 40)
        if cmd in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
            sub_map = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}
            subject = sub_map.get(cmd)
            n = datetime.now()
            
            await update.message.reply_text("📢 ውድ ተማሪዎች ውድድር መጀመሩን እየገለጽን ቀድሞ ለመለሰ 8 ነጥብ፣ ሌላ በትክክል ላገኘ 4 ነጥብ፣ ለተሳተፉ 1.5 ነጥብ ያገኛሉ።", parse_mode='HTML')
            
            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, n.strftime("%Y-%m-%d %H:%M")))
            await db.commit()

            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': subject}, name=str(chat.id))
            
            # Admin Alert
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🚀 <b>ውድድር ተጀመረ</b>\nበ: {user.first_name} (ID: {user.id})\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {n.strftime('%H:%M:%S')}", parse_mode='HTML')

# --- Admin Controls (Point 15-24, 32-36) ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    
    target_id = None
    if update.message.reply_to_message:
        match = re.search(r"ID: (\d+)", update.message.reply_to_message.text)
        if match: target_id = int(match.group(1))
        else: target_id = update.message.reply_to_message.from_user.id
    elif len(txt) > 1:
        try: target_id = int(txt[1])
        except: pass

    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "approve" and target_id:
            await db.execute("UPDATE users SET status = 'approved' WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "✅ ውድ ተማሪ ጥያቄዎ ተቀባይነት አግኝቷል! አሁን መሳተፍ ይችላሉ።")
            except: pass
            await update.message.reply_text(f"✅ ተጠቃሚ {target_id} ጸድቋል።")

        elif cmd == "anapprove" and target_id:
            await db.execute("DELETE FROM users WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "❌ ይቅርታ ጥያቄዎ ተቀባይነት አላገኘም እባክዎ ደግመው ይሞክሩ።")
            except: pass
            await update.message.reply_text(f"❌ ተጠቃሚ {target_id} ውድቅ ተደርጓል።")

        elif cmd == "log":
            async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 30") as c:
                res = "📜 <b>የውድድር ታሪክ (Logs):</b>\n"
                for r in await c.fetchall(): res += f"{r[0]} | {r[1]} | {r[2]} {r[3]}\n"
                await update.message.reply_text(res if res != "📜 <b>የውድድር ታሪክ (Logs):</b>\n" else "ምንም ሎግ የለም።", parse_mode='HTML')

        elif cmd == "hmute":
            async with db.execute("SELECT user_id, username, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL") as c:
                res = "🚫 <b>የታገዱ ዝርዝር:</b>\n"
                for r in await c.fetchall():
                    status = "❌ Blocked" if r[2] == 1 else "🔇 Muted"
                    res += f"ID: <code>{r[0]}</code> | @{r[1]} | {status}\n"
                await update.message.reply_text(res if res != "🚫 <b>የታገዱ ዝርዝር:</b>\n" else "የታገደ የለም።", parse_mode='HTML')

        elif cmd == "unmute2" or cmd == "unmute":
            if target_id:
                await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target_id,))
                await db.commit()
                async with db.execute("SELECT username FROM users WHERE user_id = ?", (target_id,)) as c:
                    u = await c.fetchone()
                    name = u[0] if u else "ተማሪ"
                await context.bot.send_message(update.effective_chat.id, f"✅ ተማሪ {name} እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ።")
                await update.message.reply_text("እገዳው ተነስቷል።")

        elif cmd == "block" and target_id:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target_id,))
            await db.commit()
            await update.message.reply_text(f"ተጠቃሚ {target_id} ታግዷል። (Blocked)")

        elif cmd == "unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል።")
            except: pass
            await update.message.reply_text("እገዳው ተነስቷል።")

        elif cmd == "info" and target_id:
            async with db.execute("SELECT user_id, username, reg_at, points FROM users WHERE user_id = ?", (target_id,)) as c:
                r = await c.fetchone()
                if r: await update.message.reply_text(f"ℹ️ <b>User Info:</b>\nID: <code>{r[0]}</code>\nName: {r[1]}\nJoined: {r[2]}\nPoints: {r[3]}", parse_mode='HTML')

        elif cmd == "pin":
            async with db.execute("SELECT user_id, username FROM users") as c:
                res = "👥 <b>የተመዘገቡ ተማሪዎች:</b>\n"
                for r in await c.fetchall(): res += f"ID: <code>{r[0]}</code> | {r[1]}\n"
                await update.message.reply_text(res, parse_mode='HTML')

        elif cmd == "rank2":
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                res = "📊 <b>ደረጃ እና ነጥብ:</b>\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
                await update.message.reply_text(res, parse_mode='HTML')

        elif cmd == "clear_rank2":
            await db.execute("UPDATE users SET points = 0")
            await db.commit()
            await update.message.reply_text("✅ ነጥብ በአዲስ ተጀምሯል።")

        elif cmd == "keep2" or cmd == "keep":
            async with db.execute("SELECT * FROM active_paths") as c:
                res = "🔍 <b>Active Paths:</b>\n"
                for r in await c.fetchall(): res += f"📍 {r[1]} (By: {r[2]}) - {r[3]}\n"
                await update.message.reply_text(res if res != "🔍 <b>Active Paths:</b>\n" else "ምንም ንቁ ውድድር የለም።", parse_mode='HTML')

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            msg = "⛔️ ከአድሚን በመጣ ትዕዛዝ መሰረት ቦቱ ለጊዜው እንዲቆም ተደርጓል። ለበለጠ መረጃ @penguiner ን ያናግሩ።"
            await broadcast_message(context, msg)

        elif cmd == "opptt":
            GLOBAL_STOP = False
            await broadcast_message(context, "✅ ቦቱ አሁን ወደ ስራ ተመልሷል።")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            await db.execute("DELETE FROM active_paths WHERE chat_id = ?", (update.effective_chat.id,))
            await db.commit()
            # Ranking report
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                res = "🏁 <b>ውድድሩ ተጠናቋል!</b>\n\n🏆 ምርጥ 15 ተወዳዳሪዎች:\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
                await update.message.reply_text(res, parse_mode='HTML')
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🏁 ውድድር በ {update.effective_user.first_name} ቆሟል።")

# --- Startup/Shutdown Notif (Point 9) ---
async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    status = "✅ ቦቱ አብርቷል" if m.new_chat_member.status == 'member' else "❌ ቦቱ አጥፍቷል"
    txt = f"{status}...\n📍 ቦታ: {update.effective_chat.title}\n👤 በ: {update.effective_user.first_name}"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, txt)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "close", "unblock", "unmute2", "unmute", "stop2", "oppt", "opptt", "hmute", "info", "keep2", "keep", "rank2", "clear_rank2", "pin", "mute", "log", "gof"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
