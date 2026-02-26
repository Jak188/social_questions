import os, json, asyncio, random, re, logging
import psycopg2
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, ChatMemberHandler, filters, MessageHandler
)

# ===================== CONFIG =====================
TOKEN = "8195013346:AAH5my3axC1JOEReN4101MeNfrDqbL-DDGY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

DATABASE_URL = "postgresql://postgres.zektvzohaujzivecjfxe:aman88%405r27@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?options=-c%20search_path%3Dpublic"

# ===================== FLASK (KEEP ALIVE) =====================
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ===================== DATABASE HELPER =====================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id BIGINT PRIMARY KEY, username TEXT, points REAL DEFAULT 0,
        status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0,
        muted_until TEXT, reg_at TEXT, last_active TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS active_polls(
        poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id BIGINT, first_winner BIGINT DEFAULT 0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS logs(
        user_id BIGINT, name TEXT, action TEXT, timestamp TEXT, date TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS active_paths(
        chat_id BIGINT PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT, subject TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS asked_questions(
        chat_id BIGINT, question_text TEXT)""")
    conn.commit()
    cur.close()
    conn.close()

# ===================== UTILS =====================
def get_user_sync(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

async def get_user(user_id):
    return get_user_sync(user_id)

async def update_activity(user_id):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_active=%s WHERE user_id=%s", (now, user_id))
    conn.commit()
    cur.close()
    conn.close()

# ===================== QUIZ ENGINE =====================
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP: return
    job = context.job
    chat_id = job.chat_id
    sub = job.data.get("subject")

    try:
        with open("questions.json", "r", encoding="utf-8") as f: all_q = json.load(f)
        filtered = [q for q in all_q if not sub or sub == "All" or q.get("subject","").lower() == sub.lower()]
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT question_text FROM asked_questions WHERE chat_id=%s", (chat_id,))
        asked = [r[0] for r in cur.fetchall()]
        
        remaining = [q for q in filtered if q['q'] not in asked]
        if not remaining:
            cur.execute("DELETE FROM asked_questions WHERE chat_id=%s", (chat_id,))
            remaining = filtered
        
        if not remaining: 
            cur.close()
            conn.close()
            return

        q = random.choice(remaining)
        msg = await context.bot.send_poll(
            chat_id, f"📚 [{q.get('subject','General')}] {q['q']}", q["o"],
            type=Poll.QUIZ, is_anonymous=False, correct_option_id=int(q["c"]),
            explanation=q.get("exp","")
        )
        cur.execute("INSERT INTO active_polls (poll_id, correct_option, chat_id, first_winner) VALUES(%s,%s,%s,0)", (msg.poll.id, int(q["c"]), chat_id))
        cur.execute("INSERT INTO asked_questions (chat_id, question_text) VALUES(%s,%s)", (chat_id, q['q']))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e: print(f"Quiz Error: {e}")

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    user_id = ans.user.id
    u = await get_user(user_id)
    
    if not u or u[3] != 'approved' or u[4] == 1: return
    await update_activity(user_id)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=%s", (ans.poll_id,))
    poll = cur.fetchone()
    
    if not poll: 
        cur.close()
        conn.close()
        return

    is_correct = ans.option_ids[0] == poll[0]
    if is_correct:
        if poll[1] == 0:
            pts = 8
            cur.execute("UPDATE active_polls SET first_winner=%s WHERE poll_id=%s", (user_id, ans.poll_id))
            await context.bot.send_message(poll[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ በትክክል በመመለሱ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
        else: pts = 4
    else: pts = 1.5

    cur.execute("UPDATE users SET points = points + %s WHERE user_id=%s", (pts, user_id))
    now = datetime.now()
    action = "✔️" if is_correct else "❎"
    cur.execute("INSERT INTO logs (user_id, name, action, timestamp, date) VALUES(%s,%s,%s,%s,%s)", (user_id, ans.user.first_name, action, now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
    conn.commit()
    cur.close()
    conn.close()

# ===================== MAIN HANDLER =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not update.message: return
    
    cmd = update.message.text.split()[0].split("@")[0].lower()
    u = await get_user(user.id)

    if cmd == "/rank2":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 20")
        rows = cur.fetchall()
        res = "🏆 ደረጃ እና ነጥብ:\n\n"
        for i, r in enumerate(rows, 1):
            res += f"{i}. {r[0]} - {r[1]} pts\n"
        cur.close()
        conn.close()
        await update.message.reply_text(res)
        return

    if u:
        if u[4] == 1:
            await update.message.reply_text(f"🚫 ከአድሚን በመጣ ትዕዛዝ መሰረት ለጊዜው ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME} ን ያናግሩ።")
            return
        if u[5]:
            try:
                m_until = datetime.fromisoformat(u[5])
                if datetime.now(timezone.utc) < m_until: return
            except: pass

    if chat.type != "private" and cmd.startswith("/") and cmd not in ["/start2", "/stop2"] and user.id not in ADMIN_IDS:
        m_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET points = points - 3.17, muted_until=%s WHERE user_id=%s", (m_time, user.id))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"⚠️ {user.first_name} በግሩፕ ውስጥ ያልተፈቀደ ትዕዛዝ በመጠቀምዎ 3.17 ነጥብ ተቀንሶ ለ17 ደቂቃ ታግደዋል።")
        return

    if GLOBAL_STOP and user.id not in ADMIN_IDS:
        await update.message.reply_text(f"⛔️ ቦቱ ከአድሚን በመጣ ትዕዛዝ ለተወሰነ ጊዜ ቆሟል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if not u:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        u_name = f"@{user.username}" if user.username else user.first_name
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users(user_id, username, reg_at, status, last_active) VALUES(%s,%s,%s,'pending',%s)",
            (user.id, u_name, now_str, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"👋 ውድ ተማሪ {user.first_name}\nምዝገባዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበልዎ ድረስ እባክዎ በትዕግስት ይጠብቁ።")
        for a in ADMIN_IDS:
            await context.bot.send_message(a, f"👤 አዲስ ተመዝጋቢ:\nID: <code>{user.id}</code>\nስም: {user.first_name}\nUsername: {u_name}\n/approve {user.id}", parse_mode="HTML")
        return

    if u[7]:
        last_active = datetime.fromisoformat(u[7])
        if datetime.now(timezone.utc) - last_active > timedelta(hours=29):
            await update.message.reply_text(f"⚠️ ውድ ተማሪ {user.first_name} የተሳትፎ ሰዓትዎ በጣም ስለቆየ ሲስተሙ አግዶዎታል። እገዳውን ለማስነሳት {ADMIN_USERNAME} ን ያናግሩ።")
            return

    if u[3] == 'pending':
        await update.message.reply_text(f"⏳ ውድ ተማሪ {user.first_name} አድሚኑ እስኪቀበልዎ ድረስ ጥያቄዎ በሂደት ላይ ነው።")
        return

    start_cmds = ["/start2", "/history_srm2", "/geography_srm2", "/mathematics_srm2", "/english_srm2"]
    all_allowed = start_cmds + ["/stop2", "/rank2"]

    if chat.type == "private" and cmd not in all_allowed and user.id not in ADMIN_IDS:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_blocked=1 WHERE user_id=%s", (user.id,))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"⚠️ የህግ ጥሰት! ያልተፈቀደ ትዕዛዝ በመጠቀሞ ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME}")
        return

    if cmd == "/stop2":
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM active_paths WHERE chat_id=%s", (chat.id,))
        conn.commit()
        
        res = "🛑 ውድድር ቆሟል።\n"
        if chat.type == "private":
            res += f"የግል ነጥብዎ: {u[2]}"
        else:
            cur.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15")
            res += "\n📊 የደረጃ ሰንጠረዥ (Top 15):\n"
            for i, r in enumerate(cur.fetchall(), 1):
                res += f"{i}. {r[0]} - {r[1]} pts\n"
        cur.close()
        conn.close()
        await update.message.reply_text(res)
        return

    if cmd in start_cmds:
        s_map = {"/history_srm2": "history", "/geography_srm2": "geography", "/mathematics_srm2": "mathematics", "/english_srm2": "english"}
        sub = s_map.get(cmd, "All")
        for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
        await update.message.reply_text(f"🚀 የ {sub} ውድድር ተጀምሯል! በየ 3 ደቂቃ ጥያቄ ይላካል።")
        context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={"subject": sub}, name=str(chat.id))
        now_t = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO active_paths (chat_id, chat_title, starter_name, start_time, subject) VALUES(%s,%s,%s,%s,%s) ON CONFLICT (chat_id) DO UPDATE SET chat_title=EXCLUDED.chat_title, starter_name=EXCLUDED.starter_name, start_time=EXCLUDED.start_time, subject=EXCLUDED.subject", (chat.id, chat.title or "Private", user.first_name, now_t, sub))
        conn.commit()
        cur.close()
        conn.close()
        for a in ADMIN_IDS: await context.bot.send_message(a, f"🚀 Start: {chat.title or 'Private'} | በ: {user.first_name} | Subject: {sub}")

# ===================== ADMIN SYSTEM =====================
async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_STOP
    if update.effective_user.id not in ADMIN_IDS: return
    m = update.message
    if not m or not m.text: return
    
    cmd = m.text.split()[0][1:].lower()
    target_id = None

    if cmd == "close":
        for j in context.job_queue.get_jobs_by_name(str(m.chat_id)): j.schedule_removal()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM active_paths WHERE chat_id=%s", (m.chat_id,))
        conn.commit()
        cur.close()
        conn.close()
        await m.reply_text("🛑 ውድድሩ በአድሚን ትዕዛዝ ቆሟል።")
        return

    if m.reply_to_message:
        match = re.search(r"ID: (\d+)|ID:<code>(\d+)</code>", m.reply_to_message.text)
        if match: target_id = int(match.group(1) or match.group(2))
    if not target_id and len(m.text.split()) > 1:
        try: target_id = int(m.text.split()[1])
        except: pass

    conn = get_db_connection()
    cur = conn.cursor()
    if cmd == "gof":
        cur.execute("SELECT user_id, username, reg_at FROM users WHERE status='pending'")
        rows = cur.fetchall()
        if not rows:
            await m.reply_text("የምዝገባ ጥያቄ ያቀረበ አዲስ ተማሪ የለም።")
        else:
            res = "📝 የምዝገባ ጥያቄ ያቀረቡ ተማሪዎች ዝርዝር፦\n\n"
            for r in rows: res += f"👤 ስም: {r[1]}\nID: <code>{r[0]}</code>\nቀን: {r[2]}\n"
            await m.reply_text(res, parse_mode="HTML")

    elif cmd == "approve" and target_id:
        cur.execute("UPDATE users SET status='approved' WHERE user_id=%s", (target_id,))
        conn.commit()
        await m.reply_text(f"ተማሪ {target_id} ተቀባይነት አግኝቷል ✅")
        try: 
            await context.bot.send_message(target_id, "✅ ምዝገባዎ ተቀባይነት አግኝቷል። አሁን መወዳደር ይችላሉ!")
        except: 
            pass

    elif cmd == "anapprove" and target_id:
        cur.execute("DELETE FROM users WHERE user_id=%s", (target_id,))
        conn.commit()
        await m.reply_text(f"ተማሪ {target_id} ውድቅ ተደርጓል ❌")

    elif cmd == "block" and target_id:
        cur.execute("UPDATE users SET is_blocked=1 WHERE user_id=%s", (target_id,))
        conn.commit()
        await m.reply_text(f"🚫 ተማሪ {target_id} ታግዷል።")

    elif cmd == "unblock" and target_id:
        cur.execute("UPDATE users SET is_blocked=0 WHERE user_id=%s", (target_id,))
        conn.commit()
        await m.reply_text(f"✅ ተማሪ {target_id} እገዳው ተነስቷል።")

    elif cmd == "oppt": GLOBAL_STOP = True; await m.reply_text("⛔️ Global Stop በርቷል።")
    elif cmd == "opptt": GLOBAL_STOP = False; await m.reply_text("✅ Global Stop ተነስቷል።")

    elif cmd == "yam":
        broadcast_text = m.text.replace("/yam", "").strip()
        cur.execute("SELECT user_id FROM users WHERE status='approved'")
        users = cur.fetchall()
        cur.execute("SELECT chat_id FROM active_paths")
        groups = cur.fetchall()
        all_targets = set([u[0] for u in users] + [g[0] for g in groups])
        count = 0
        for target in all_targets:
            try:
                if m.reply_to_message:
                    await context.bot.copy_message(chat_id=target, from_chat_id=m.chat_id, message_id=m.reply_to_message.message_id, caption=broadcast_text if broadcast_text else m.reply_to_message.caption)
                elif broadcast_text: await context.bot.send_message(chat_id=target, text=broadcast_text)
                count += 1
                await asyncio.sleep(0.05)
            except: continue
        await m.reply_text(f"📢 መልእክቱ ለ {count} ተቀባዮች ተልኳል!")

    elif cmd == "clear_rank2":
        cur.execute("UPDATE users SET points = 0")
        conn.commit()
        await m.reply_text("Rankings Cleared 🧹")

    elif cmd == "log":
        cur.execute("SELECT name, action, timestamp, date FROM logs ORDER BY date DESC, timestamp DESC LIMIT 20")
        rows = cur.fetchall()
        if not rows: await m.reply_text("ምንም አይነት የሎግ መረጃ የለም።")
        else:
            res = "📜 የሙሉ ተወዳዳሪዎች ዝርዝር ታሪክ፦\n\n"
            for r in rows: res += f"👤 {r[0]} | {r[1]} | ⏰ {r[2]} ({r[3]})\n"
            await m.reply_text(res)

    elif cmd == "clear_log":
        cur.execute("DELETE FROM logs")
        conn.commit()
        await m.reply_text("Log Cleared 🧹")

    elif cmd == "keep":
        cur.execute("SELECT * FROM active_paths")
        rows = cur.fetchall()
        if not rows: await m.reply_text("አሁን ላይ በምንም አይነት ግሩፕ ወይም ሰው ላይ ቦቱ እየሰራ አይደለም።")
        else:
            res = "📍 አሁን ቦቱ ACTIVE የሆነባቸው መንገዶች፦\n\n"
            for r in rows: res += f"🔹 ቦታ: {r[1]} (ID: <code>{r[0]}</code>)\n👤 የጀመረው: {r[2]}\n⏰ ሰዓት: {r[3]}\n📚 ትምህርት: {r[4]}\n\n"
            await m.reply_text(res, parse_mode="HTML")

    elif cmd == "pin":
        cur.execute("SELECT user_id, username FROM users")
        u_rows = cur.fetchall()
        cur.execute("SELECT chat_id, chat_title FROM active_paths")
        g_rows = cur.fetchall()
        res = f"📊 አጠቃላይ መረጃ፦\n\n👥 ተመዝጋቢዎች ({len(u_rows)}):\n"
        for u in u_rows: res += f"- {u[1]} (ID: {u[0]})\n"
        res += f"\n📍 ቦቱ ያለባቸው ግሩፖች ({len(g_rows)}):\n"
        for g in g_rows: res += f"- {g[1]} (ID: {g[0]})\n"
        await m.reply_text(res)

    elif cmd == "hmute":
        cur.execute("SELECT user_id, username, is_blocked, muted_until FROM users WHERE is_blocked=1 OR muted_until IS NOT NULL")
        rows = cur.fetchall()
        if not rows: await m.reply_text("የታገደ ወይም Mute የሆነ ሰው የለም።")
        else:
            res = "🔇 የታገዱ/Mute የሆኑ ዝርዝር፦\n\n"
            for r in rows:
                status = "🚫 Blocked" if r[2] == 1 else "🔇 Muted"
                res += f"👤 {r[1]} | ID: <code>{r[0]}</code> | {status}\n"
            await m.reply_text(res, parse_mode="HTML")

    elif cmd == "info" and target_id:
        u_info = await get_user(target_id)
        if u_info:
            res = f"ℹ️ የተጠቃሚ መረጃ፦\n\n👤 ስም: {u_info[1]}\n🆔 ID: <code>{u_info[0]}</code>\n💰 ነጥብ: {u_info[2]}\n📅 የተመዘገበበት: {u_info[6]}\n⏳ መጨረሻ የታየው: {u_info[7]}"
            await m.reply_text(res, parse_mode="HTML")
    
    cur.close()
    conn.close()

# ===================== RUNNER =====================
def main():
    init_db()
    keep_alive()
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2","rank2"], start_handler))
    bot_app.add_handler(CommandHandler(["approve","anapprove","block","unblock","log","clear_log","oppt","opptt","pin","keep","hmute","info","clear_rank2","close","gof"], admin_ctrl))
    bot_app.add_handler(PollAnswerHandler(receive_answer))
    bot_app.run_polling()

if __name__ == "__main__":
    main()
