import os
import json
import asyncio
import random
import re
import logging
import psycopg2
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, filters, MessageHandler
)

# ===================== CONFIGURATION =====================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# Database Connection (Neon PostgreSQL)
DATABASE_URL = "postgresql://neondb_owner:npg_aRi7qp2QdYWr@ep-red-pond-ai6ow5wf-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require"

# ===================== FLASK KEEP ALIVE =====================
app = Flask(__name__)
@app.route('/')
def home(): return "Quiz Bot is Online and Running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== DATABASE INITIALIZATION =====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Users Table
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id BIGINT PRIMARY KEY, 
        username TEXT, 
        first_name TEXT,
        points REAL DEFAULT 0,
        status TEXT DEFAULT 'pending', 
        is_blocked INTEGER DEFAULT 0,
        muted_until TEXT, 
        reg_at TEXT, 
        last_active TEXT)""")
    # Active Polls Tracking
    cur.execute("""CREATE TABLE IF NOT EXISTS active_polls(
        poll_id TEXT PRIMARY KEY, 
        correct_option INTEGER, 
        chat_id BIGINT, 
        first_winner BIGINT DEFAULT 0)""")
    # Logs for Activities
    cur.execute("""CREATE TABLE IF NOT EXISTS logs(
        user_id BIGINT, 
        name TEXT, 
        action TEXT, 
        timestamp TEXT, 
        date TEXT)""")
    # Path Tracking for Groups/Users
    cur.execute("""CREATE TABLE IF NOT EXISTS active_paths(
        chat_id BIGINT PRIMARY KEY, 
        chat_title TEXT, 
        starter_id BIGINT,
        starter_name TEXT, 
        start_time TEXT, 
        subject TEXT)""")
    # Asked Questions tracking per chat
    cur.execute("""CREATE TABLE IF NOT EXISTS asked_questions(
        chat_id BIGINT, 
        question_text TEXT)""")
    conn.commit()
    cur.close()
    conn.close()

# ===================== CORE UTILITIES =====================
async def is_admin(user_id):
    return user_id in ADMIN_IDS

async def get_user_data(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

async def update_last_active(user_id):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_active=%s WHERE user_id=%s", (now, user_id))
    conn.commit()
    cur.close()
    conn.close()

def extract_id_from_text(text):
    if not text: return None
    match = re.search(r"ID:\s*(\d+)", text)
    return int(match.group(1)) if match else None

# ===================== QUIZ LOGIC =====================
async def send_quiz_job(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    
    chat_id = context.job.chat_id
    data = context.job.data
    subject = data.get("subject", "All")

    try:
        with open("questions.json", "r", encoding="utf-8") as f:
            all_questions = json.load(f)
        
        # Filter by subject
        if subject != "All":
            pool = [q for q in all_questions if q.get("subject", "").lower() == subject.lower()]
        else:
            pool = all_questions

        # Fetch already asked questions for this chat
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT question_text FROM asked_questions WHERE chat_id=%s", (chat_id,))
        asked = [r[0] for r in cur.fetchall()]
        
        # Priority: Not yet asked
        remaining = [q for q in pool if q['q'] not in asked]
        if not remaining:
            cur.execute("DELETE FROM asked_questions WHERE chat_id=%s", (chat_id,))
            remaining = pool # Reset if all questions finished
        
        if not remaining:
            cur.close()
            conn.close()
            return

        q = random.choice(remaining)
        poll_msg = await context.bot.send_poll(
            chat_id, 
            f"📚 [{q.get('subject', 'General')}] {q['q']}", 
            q["o"],
            type=Poll.QUIZ, 
            is_anonymous=False, 
            correct_option_id=int(q["c"]),
            explanation=q.get("exp", "ትክክለኛውን መልስ ይምረጡ!")
        )

        cur.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id) VALUES (%s, %s, %s)", 
                    (poll_msg.poll.id, int(q["c"]), chat_id))
        cur.execute("INSERT INTO asked_questions (chat_id, question_text) VALUES (%s, %s)", (chat_id, q['q']))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Quiz Error: {e}")

# ===================== POLL ANSWER HANDLER =====================
async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    user = await get_user_data(user_id)

    # Validation
    if not user or user[4] != 'approved' or user[5] == 1: return
    
    # 29-hour inactivity check
    if user[8]:
        last_act = datetime.fromisoformat(user[8])
        if datetime.now(timezone.utc) - last_act > timedelta(hours=29):
            await context.bot.send_message(user_id, f"⚠️ ውድ ተማሪ {user[2]} የተሳትፎ ሰዓትዎ በጣም ስለቆየ ሲስተሙ አግዶዎታል እገዳዎትን ለማስነሳት {ADMIN_USERNAME} ን ይጠይቁ : እናመሰግናለን")
            return

    await update_last_active(user_id)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=%s", (ans.poll_id,))
    poll_data = cur.fetchone()
    
    if not poll_data:
        cur.close()
        conn.close()
        return

    is_correct = ans.option_ids[0] == poll_data[0]
    points_to_add = 0
    action_mark = "❎"

    if is_correct:
        action_mark = "✔️"
        if poll_data[1] == 0: # First winner
            points_to_add = 8
            cur.execute("UPDATE active_polls SET first_winner=%s WHERE poll_id=%s", (user_id, ans.poll_id))
            await context.bot.send_message(poll_data[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ በትክክል በመመለሱ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
        else:
            points_to_add = 4
    else:
        points_to_add = 1.5

    cur.execute("UPDATE users SET points = points + %s WHERE user_id=%s", (points_to_add, user_id))
    cur.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES (%s, %s, %s, %s, %s)",
                (user_id, ans.user.first_name, action_mark, datetime.now().strftime("%H:%M:%S"), datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    cur.close()
    conn.close()

# ===================== COMMAND HANDLERS =====================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text.lower()
    
    # Identify subject
    subject = "All"
    if "history" in text: subject = "history"
    elif "geography" in text: subject = "geography"
    elif "mathematics" in text: subject = "mathematics"
    elif "english" in text: subject = "english"

    user_db = await get_user_data(user.id)

    # 1. Registration Check
    if not user_db:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, username, first_name, reg_at, status, last_active) VALUES (%s, %s, %s, %s, 'pending', %s)",
                    (user.id, f"@{user.username}" if user.username else "NoUser", user.first_name, now_str, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"👋 ውድ ተማሪ {user.first_name} ለምዝገባ ጥያቄዎ በትክክል ደርሶናል። አድሚኑ እስኪቀበልዎ ድረስ እባክዎ በትዕግስት ይጠብቁ።")
        
        # Notify Admin
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"👤 አዲስ የምዝገባ ጥያቄ (ID: {user.id}):\nስም: {user.first_name}\nUsername: @{user.username}\n\nለመቀበል Reply: /approve")
        return

    # 2. Pending Status
    if user_db[4] == 'pending':
        await update.message.reply_text(f"⏳ ውድ ተማሪ {user.first_name} አድሚኑ ለጊዜው ስራ ስለበዛበት ነው፤ ጥያቄዎ ተቀባይነት ሲያገኝ እናሳውቅዎታለን። እናመሰግናለን።")
        return

    # 3. Blocked Status
    if user_db[5] == 1:
        await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ መሰረት ለጊዜው ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
        return

    # 4. Inactivity Check
    if user_db[8]:
        last_act = datetime.fromisoformat(user_db[8])
        if datetime.now(timezone.utc) - last_act > timedelta(hours=29):
            await update.message.reply_text(f"⚠️ ውድ ተማሪ {user.first_name} የተሳትፎ ሰዓትዎ በጣም ስለቆየ ሲስተሙ አግዶዎታል እገዳዎትን ለማስነሳት {ADMIN_USERNAME} ን ይጠይቁ።")
            return

    # 5. Global Stop Check
    if GLOBAL_STOP and not await is_admin(user.id):
        await update.message.reply_text(f"🚫 ውድድሩ ከአድሚን በመጣ ትዕዛዝ ለጊዜው ተቋርጧል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
        return

    # 6. Command Permissions
    allowed_private = ["/start2", "/stop2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2", "/rank2"]
    if chat.type == "private" and update.message.text.split()[0] not in allowed_private and not await is_admin(user.id):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_blocked=1 WHERE user_id=%s", (user.id,))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"⚠️ የህግ ጥሰት! ያልተፈቀደ ትዕዛዝ በመጠቀሞ ታግደዋል። {ADMIN_USERNAME} ን ያናግሩ።")
        return

    if chat.type != "private" and not await is_admin(user.id) and update.message.text.split()[0] not in ["/start2", "/stop2"]:
        # Penalty for wrong group command
        conn = get_db_connection()
        cur = conn.cursor()
        m_until = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        cur.execute("UPDATE users SET points = points - 3.17, muted_until=%s WHERE user_id=%s", (m_until, user.id))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"⚠️ {user.first_name} በግሩፕ ውስጥ ያልተፈቀደ ትዕዛዝ በመጠቀምዎ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    # 7. Start Quiz
    for job in context.job_queue.get_jobs_by_name(str(chat.id)): job.schedule_removal()
    
    # Interval set to 3 minutes
    context.job_queue.run_repeating(send_quiz_job, interval=180, first=1, chat_id=chat.id, data={"subject": subject}, name=str(chat.id))
    
    now_t = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO active_paths (chat_id, chat_title, starter_id, starter_name, start_time, subject) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (chat_id) DO UPDATE SET subject=EXCLUDED.subject",
                (chat.id, chat.title if chat.title else "Private", user.id, user.first_name, now_t, subject))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text(f"🚀 የ {subject} ውድድር በ {user.first_name} ተጀምሯል! በየ 3 ደቂቃ ጥያቄ ይላካል።")
    
    # Notify Admin
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"✅ ውድድር ተጀመረ!\nቦታ: {chat.title if chat.title else 'Private'}\nID: {chat.id}\nበ: {user.first_name} (ID: {user.id})\nትምህርት: {subject}\nሰዓት: {now_t}")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    for job in context.job_queue.get_jobs_by_name(str(chat.id)): job.schedule_removal()
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM active_paths WHERE chat_id=%s", (chat.id,))
    conn.commit()

    # Result Display
    if chat.type == "private":
        cur.execute("SELECT points FROM users WHERE user_id=%s", (user.id,))
        pts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE points > %s", (pts,))
        rank = cur.fetchone()[0] + 1
        await update.message.reply_text(f"🛑 ውድድሩ ቆሟል።\nየእርስዎ ነጥብ: {pts}\nደረጃ: {rank}\n\nእንደገና ለማስጀመር /start2 ይበሉ።")
    else:
        cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15")
        rows = cur.fetchall()
        res = "📊 የደረጃ ሰንጠረዥ (Best of 15):\n\n"
        for i, r in enumerate(rows, 1):
            res += f"{i}. {r[0]} - {r[1]} pts\n"
        await update.message.reply_text(f"🛑 ውድድሩ ቆሟል።\n\n{res}")

    cur.close()
    conn.close()
    
    # Notify Admin
    for admin in ADMIN_IDS:
        await context.bot.send_message(admin, f"🛑 ውድድር ቆመ በ: {chat.title if chat.title else 'Private'} (ID: {chat.id})")

# ===================== ADMIN CONTROLS =====================
async def admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    
    msg = update.message
    cmd_raw = msg.text.split()[0].lower()
    cmd = cmd_raw[1:] # remove /
    
    target_id = None
    # Extract ID from reply or text
    if msg.reply_to_message:
        target_id = extract_id_from_text(msg.reply_to_message.text)
    
    if not target_id and len(msg.text.split()) > 1:
        try: target_id = int(msg.text.split()[1])
        except: pass

    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Approve/Anapprove
    if cmd == "approve" and target_id:
        cur.execute("UPDATE users SET status='approved' WHERE user_id=%s", (target_id,))
        conn.commit()
        await msg.reply_text(f"✅ ተማሪ {target_id} ተቀባይነት አግኝቷል።")
        try: await context.bot.send_message(target_id, "✅ ምዝገባዎ ተቀባይነት አግኝቷል! አሁን መሳተፍ ይችላሉ።")
        except: pass
    
    elif cmd == "anapprove" and target_id:
        cur.execute("DELETE FROM users WHERE user_id=%s", (target_id,))
        conn.commit()
        await msg.reply_text(f"❌ ተማሪ {target_id} ውድቅ ተደርጓል።")
        try: await context.bot.send_message(target_id, "❌ የምዝገባ ጥያቄዎ ተቀባይነት አላገኘም፤ እባክዎ እንደገና ይሞክሩ።")
        except: pass

    # 2. Block/Unblock
    elif cmd == "block" and target_id:
        cur.execute("UPDATE users SET is_blocked=1 WHERE user_id=%s", (target_id,))
        conn.commit()
        await msg.reply_text(f"🚫 ID: {target_id} ታግዷል።")
        try: await context.bot.send_message(target_id, f"🚫 ከአድሚን በመጣ ትዕዛዝ ታግደዋል፤ @penguiner ን ያናግሩ።")
        except: pass

    elif cmd == "unblock" and target_id:
        cur.execute("UPDATE users SET is_blocked=0, last_active=%s WHERE user_id=%s", (datetime.now(timezone.utc).isoformat(), target_id))
        conn.commit()
        await msg.reply_text(f"🔓 ID: {target_id} እገዳው ተነስቷል።")
        try: await context.bot.send_message(target_id, "🔓 እገዳዎ ተነስቷል! በድጋሚ ላለመሳሳት ይሞክሩ።")
        except: pass

    # 3. Global Stop/Start
    elif cmd == "oppt":
        global GLOBAL_STOP
        GLOBAL_STOP = True
        await msg.reply_text("⛔️ Global Stop: ቦቱ በሁሉም ቦታ ቆሟል።")
    elif cmd == "opptt":
        GLOBAL_STOP = False
        await msg.reply_text("✅ Global Start: ቦቱ ወደ ስራ ተመልሷል።")

    # 4. Status Commands
    elif cmd == "pin":
        cur.execute("SELECT first_name, user_id, username FROM users")
        u = cur.fetchall()
        cur.execute("SELECT chat_title, chat_id FROM active_paths")
        g = cur.fetchall()
        res = f"📊 PIN መረጃ:\n\n👥 ተመዝጋቢዎች ({len(u)}):\n"
        for r in u: res += f"- {r[0]} (ID: {r[1]}) @{r[2]}\n"
        res += f"\n📍 አክቲቭ ግሩፖች ({len(g)}):\n"
        for r in g: res += f"- {r[0]} (ID: {r[1]})\n"
        await msg.reply_text(res)

    elif cmd == "gof":
        cur.execute("SELECT first_name, user_id, username FROM users WHERE status='pending'")
        rows = cur.fetchall()
        res = "📝 የምዝገባ ጥያቄዎች:\n\n"
        for r in rows: res += f"👤 {r[0]} | ID: {r[1]} | @{r[2]}\n"
        await msg.reply_text(res if rows else "ምንም ጥያቄ የለም።")

    elif cmd == "hmute":
        cur.execute("SELECT first_name, user_id, username, is_blocked, muted_until FROM users")
        res = "🔇 የታገዱ ዝርዝር:\n\n"
        for r in cur.fetchall():
            status = ""
            if r[3] == 1: status = "🚫 Blocked"
            elif r[4] and datetime.now(timezone.utc) < datetime.fromisoformat(r[4]): status = "🔇 Muted"
            if status: res += f"👤 {r[0]} (ID: {r[1]}) - {status}\n"
        await msg.reply_text(res)

    elif cmd == "log": #
        cur.execute("SELECT name, action, timestamp, date FROM logs ORDER BY date DESC, timestamp DESC LIMIT 30")
        res = "📜 የጥያቄዎች ሎግ (ያለፉት 30):\n\n"
        for r in cur.fetchall(): res += f"{r[1]} {r[0]} | {r[2]} | {r[3]}\n"
        await msg.reply_text(res)

    cur.close()
    conn.close()

# ===================== RANKING =====================
async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 20")
    rows = cur.fetchall()
    res = "🏆 የደረጃ ሰንጠረዥ (Top 20):\n\n"
    for i, r in enumerate(rows, 1):
        res += f"{i}. {r[0]} - {r[1]} pts\n"
    cur.close()
    conn.close()
    await update.message.reply_text(res)

async def clear_rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id): return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET points = 0")
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("🧹 ሁሉም ነጥቦች ተሰርዘው በአዲስ ተጀምረዋል።")

# ===================== MAIN RUNNER =====================
def main():
    init_db()
    keep_alive()
    bot = Application.builder().token(TOKEN).build()

    # User Commands
    user_cmds = ["start2", "stop2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2", "rank2"]
    bot.add_handler(CommandHandler(user_cmds, start_cmd))
    bot.add_handler(CommandHandler("stop2", stop_cmd))
    bot.add_handler(CommandHandler("rank2", rank_cmd))

    # Admin Commands
    admin_cmds = ["approve", "anapprove", "block", "unblock", "oppt", "opptt", "pin", "gof", "hmute", "log", "clear_rank2", "keep", "info", "close"]
    bot.add_handler(CommandHandler(admin_cmds, admin_dispatch))

    # Handlers
    bot.add_handler(PollAnswerHandler(handle_poll_answer))
    
    print("Bot is fully active...")
    bot.run_polling()

if __name__ == "__main__":
    main()
