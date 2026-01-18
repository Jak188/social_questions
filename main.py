import os, json, asyncio, random, aiosqlite, re
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, ChatMemberHandler, filters

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- Configuration ---
TOKEN = "YOUR_BOT_TOKEN_HERE" # <--- የእርስዎን ቶክን እዚህ ይተኩ
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
    """ሁሉንም ተጠቃሚዎች እና ግሩፖች ከዳታቤዝ ያወጣል"""
    chats = set()
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT user_id FROM users") as c:
            for r in await c.fetchall(): chats.add(r[0])
        async with db.execute("SELECT chat_id FROM active_paths") as c:
            for r in await c.fetchall(): chats.add(r[0])
    return chats

async def broadcast_message(context, text):
    """ለሁሉም ተጠቃሚዎች እና ግሩፖች መልዕክት ይልካል"""
    chat_ids = await get_all_chats()
    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=text)
            await asyncio.sleep(0.05) # ፍጥነቱን ለመቀነስ (Telegram limit እንዳይመታ)
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
            msg = await context.bot.send_poll(job.chat_id, f"[{q.get('subject', 'General')}] {q['q']}", q['o'], 
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
            await context.bot.send_message(p_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        now = datetime.now()
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES (?, ?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
        await db.commit()

# --- Core Logic ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    cmd = update.message.text.split('@')[0].lower() if update.message.text else ""

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"ከአድሚን በሰጠው ትእዛዝ መሰረት ቦቱ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
        return

    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user.id,)) as c: u_data = await c.fetchone()

        if not u_data:
            reg_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("INSERT INTO users (user_id, username, status, reg_at) VALUES (?, ?, 'pending', ?)", (user.id, user.first_name, reg_time))
            await db.commit()
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} የምዝገባ ጥያቄዎ በሂደት ላይ ነው ጥያቄውን አድሚኑ እስኪቀበልዎ እባክዎ በትእግስት ይጠብቁ")
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"👤 አዲስ ተመዝጋቢ:\nስም: {user.first_name}\nID: {user.id}\nUsername: @{user.username}")
            return

        if u_data[3] == 'pending':
            await update.message.reply_text(f"ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው ቢዚ ነው ጥያቄዎ ተቀባይነት ሲያገኝ የምናሳውቅዎ ይሆናል እናመሰግናለን።")
            return

        if u_data[4] == 1:
            await update.message.reply_text(f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ")
            return

        # Rules for non-admins
        if user.id not in ADMIN_IDS:
            allowed = ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2", "/stop2", "/keep"]
            if chat.type == "private" and cmd not in allowed:
                await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user.id,))
                await db.commit()
                await update.message.reply_text(f"የህግ ጥሰት፡ ከተፈቀደልዎ ትእዛዝ ውጭ አዘዋል። በዚሁ ምክንያት ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
                for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🚫 ተማሪ {user.first_name} (ID: {user.id}) ያልተፈቀደ ትእዛዝ በመጠቀሙ ታግዷል።")
                return
            elif chat.type != "private" and cmd not in ["/start2", "/stop2"] and cmd.startswith('/'):
                mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
                await db.execute("UPDATE users SET points = points - 3.17, muted_until = ? WHERE user_id = ?", (mute_to, user.id))
                await db.commit()
                await update.message.reply_text(f"የህግ ጥሰት.. {user.first_name} የአድሚን ትእዛዝ በመንካትህ 3.17 ነጥብ ተቀንሶብሃል ለ17 ደቂቃ ታግደሃል")
                for adm in ADMIN_IDS: await context.bot.send_message(adm, f"⚠️ ተማሪ {user.first_name} (ID: {user.id}) ከግሩፕ {chat.title} ታግዷል። እገዳውን ለማንሳት replay አድርገህ /unmute2 በል")
                return

        # Start Competition
        if cmd in ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]:
            sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
            n = datetime.now()
            inf = f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name} (ID: {user.id})\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {n.strftime('%H:%M:%S')} | ቀን: {n.strftime('%Y-%m-%d')}"
            for adm in ADMIN_IDS: await context.bot.send_message(adm, inf)

            await db.execute("INSERT OR REPLACE INTO active_paths VALUES (?, ?, ?, ?)", (chat.id, chat.title if chat.title else "Private", user.first_name, n.strftime("%Y-%m-%d %H:%M")))
            await db.commit()

            jobs = context.job_queue.get_jobs_by_name(str(chat.id))
            for j in jobs: j.schedule_removal()
            context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={'subject': sub}, name=str(chat.id))
            await update.message.reply_text("ዉድ ተማሪዎች ውድድር መጀመሩን እየገለጽን ቀድሞ ለመለሰ 8 ነጥብ፣ ሌላ በትክክል ላገኘ 4 ነጥብ፣ ለተሳተፉ 1.5 ነጥብ ያገኛሉ።")

# --- Admin Controls ---
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    txt = update.message.text.split()
    cmd = txt[0][1:].lower()
    
    # ፎቶው ላይ ያሉት ትዕዛዞች በReply እንዲሰሩ
    target_id = None
    if update.message.reply_to_message:
        # መልዕክቱ የቦቱ ፎርዋርድ ከሆነ ከጽሁፉ ውስጥ ID መፈለግ
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
            try: await context.bot.send_message(target_id, "ውድ ተማሪ ጥያቄዎ ተቀባይነት አግኝቷል! አሁን መሳተፍ ይችላሉ።")
            except: pass
            await update.message.reply_text(f"ተጠቃሚ {target_id} ጸድቋል።")

        elif cmd == "anapprove" and target_id:
            await db.execute("DELETE FROM users WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "ይቅርታ ጥያቄዎ ተቀባይነት አላገኘም እባክዎ ደግመው ይሞክሩ።")
            except: pass
            await update.message.reply_text(f"ተጠቃሚ {target_id} ውድቅ ተደርጓል።")

        elif (cmd == "mute" or cmd == "mute2") and target_id:
            mute_to = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
            await db.execute("UPDATE users SET muted_until = ? WHERE user_id = ?", (mute_to, target_id))
            await db.commit()
            await update.message.reply_text(f"ተጠቃሚ {target_id} ለ17 ደቂቃ ታግዷል።")

        elif (cmd == "unmute" or cmd == "unmute2") and target_id:
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "እገዳዎ በአድሚኑ ትእዛዝ ተነስቶልዎታል በድጋሚ ላለመሳሳት ይሞክሩ።")
            except: pass
            await update.message.reply_text("እገዳው ተነስቷል።")

        elif (cmd == "block" or cmd == "close") and target_id:
            # close ከተባለ ውድድሩንም ያቆማል
            if cmd == "close":
                for j in context.job_queue.get_jobs_by_name(str(target_id)): j.schedule_removal()
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, f"ከአድሚን በመጣ ትእዛዝ መሰረት ለጊዜው ታግደዋል ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
            except: pass
            await update.message.reply_text(f"ተጠቃሚ/ግሩፕ {target_id} ታግዷል።")

        elif cmd == "unblock" and target_id:
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (target_id,))
            await db.commit()
            try: await context.bot.send_message(target_id, "እገዳዎ ተነስቷል።")
            except: pass
            await update.message.reply_text("እገዳው ተነስቷል።")

        elif cmd == "oppt":
            global GLOBAL_STOP
            GLOBAL_STOP = True
            msg = f"ከአድሚን በመጣ ትእዛዝ መሰረት ቦቱ ለጊዜው እንዲቆም ተደርጓል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።"
            await broadcast_message(context, msg)
            await update.message.reply_text("ቦቱ ለሁሉም ቆሟል።")
        
        elif cmd == "opptt":
            GLOBAL_STOP = False
            msg = "ቦቱ አሁን ወደ ስራ ተመልሷል። በደስታ ተሳተፉ!"
            await broadcast_message(context, msg)
            await update.message.reply_text("ቦቱ ለሁሉም ተከፍቷል።")

        elif cmd == "stop2":
            cid = str(update.effective_chat.id)
            for j in context.job_queue.get_jobs_by_name(cid): j.schedule_removal()
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                rows = await c.fetchall()
                res = "🏁 ውድድሩ ተጠናቋል!\n\n🏆 ምርጥ 15 ተወዳዳሪዎች፡\n"
                for i, r in enumerate(rows, 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
                await update.message.reply_text(res)
            for adm in ADMIN_IDS: await context.bot.send_message(adm, f"🏁 ውድድር በ {update.effective_user.first_name} ቆሟል።")

        elif cmd == "rank2":
            async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as c:
                res = "📊 የደረጃ ሰንጠረዥ፡\n"
                for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} ነጥብ\n"
                await update.message.reply_text(res)

        elif cmd == "keep2":
            async with db.execute("SELECT * FROM active_paths") as c:
                rows = await c.fetchall()
                res = "🔍 ንቁ ውድድሮች፡\n"
                for p in rows: res += f"ቦታ: {p[1]} (ID: {p[0]}) | በ: {p[2]} የጀመረ፡ {p[3]}\n"
                await update.message.reply_text(res if len(res)>15 else "ምንም ንቁ ውድድር የለም።")

# --- Startup ---
async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    status = "✅ ቦቱ አብርቷል" if m.new_chat_member.status == 'member' else "❌ ቦቱ አጥፍቷል"
    txt = f"{status}...\nበ፡ {update.effective_user.first_name} (ID: {update.effective_user.id})"
    for adm in ADMIN_IDS: await context.bot.send_message(adm, txt)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["approve", "anapprove", "block", "close", "unblock", "unmute2", "unmute", "stop2", "oppt", "opptt", "hmute", "info", "keep2", "rank2", "clear_rank2", "pin", "mute"], admin_ctrl))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
