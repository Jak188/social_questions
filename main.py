# ===================== IMPORTS =====================
import os, json, asyncio, random, re
import aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread

from telegram import Update, Poll
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, ChatMemberHandler
)

# ===================== FLASK KEEP ALIVE =====================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Online!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run, daemon=True).start()

# ===================== CONFIG =====================
TOKEN = os.getenv("8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY")  # 🔐 SAFE
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"
GLOBAL_STOP = False

# ===================== DATABASE =====================
async def init_db():
    async with aiosqlite.connect("quiz_bot.db") as db:
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
            user_id INTEGER,
            name TEXT,
            action TEXT,
            timestamp TEXT,
            date TEXT
        )""")

        await db.commit()

# ===================== QUIZ =====================
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
    if GLOBAL_STOP:
        return

    job = context.job
    try:
        with open("questions.json", "r", encoding="utf-8") as f:
            all_q = json.load(f)

        sub = job.data.get("subject")
        questions = [q for q in all_q if q.get("subject","").lower()==sub] if sub else all_q
        if not questions:
            return

        q = random.choice(questions)

        msg = await context.bot.send_poll(
            job.chat_id,
            f"📚 [{q.get('subject','General')}] {q['q']}",
            q["o"],
            type=Poll.QUIZ,
            is_anonymous=False,
            correct_option_id=int(q["c"]),
            explanation=q.get("exp","")
        )

        async with aiosqlite.connect("quiz_bot.db") as db:
            await db.execute(
                "INSERT INTO active_polls VALUES(?,?,?,0)",
                (msg.poll.id, int(q["c"]), job.chat_id)
            )
            await db.commit()

    except Exception as e:
        print("Quiz Error:", e)

# ===================== ANSWER =====================
async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer

    async with aiosqlite.connect("quiz_bot.db") as db:

        async with db.execute("SELECT * FROM users WHERE user_id=?", (ans.user.id,)) as c:
            user = await c.fetchone()

        if not user or user[3] != "approved" or user[4] == 1:
            return

        if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]):
            return

        async with db.execute(
            "SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?",
            (ans.poll_id,)
        ) as c:
            poll = await c.fetchone()

        if not poll:
            return

        is_correct = ans.option_ids[0] == poll[0]

        if is_correct and poll[1] == 0:
            points = 8
            await db.execute(
                "UPDATE active_polls SET first_winner=? WHERE poll_id=?",
                (ans.user.id, ans.poll_id)
            )
            await context.bot.send_message(
                poll[2],
                f"🏆 {ans.user.first_name} ቀድሞ መልሶ 8 ነጥብ አግኝቷል!"
            )
        elif is_correct:
            points = 4
        else:
            points = 1.5

        await db.execute(
            "UPDATE users SET points = points + ? WHERE user_id=?",
            (points, ans.user.id)
        )

        now = datetime.now()
        await db.execute(
            "INSERT INTO logs VALUES(?,?,?,?,?)",
            (
                ans.user.id,
                ans.user.first_name,
                "✔️" if is_correct else "❎",
                now.strftime("%H:%M:%S"),
                now.strftime("%Y-%m-%d")
            )
        )

        await db.commit()

# ===================== START =====================
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    cmd = update.message.text.split("@")[0].lower()

    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user.id,)) as c:
            u = await c.fetchone()

        if not u:
            await db.execute(
                "INSERT INTO users(user_id, username, reg_at) VALUES(?,?,?)",
                (user.id, user.first_name,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            await db.commit()

            await update.message.reply_text(
                f"👋 ውድ {user.first_name}\nምዝገባዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበል ይጠብቁ።"
            )

            for a in ADMIN_IDS:
                await context.bot.send_message(
                    a,
                    f"👤 New Registration\nName:{user.first_name}\nID:{user.id}"
                )
            return

        if u[3] == "pending":
            await update.message.reply_text(
                "⏳ አድሚኑ busy ነው። በትእግስት ይጠብቁ።"
            )
            return

        if u[4] == 1:
            await update.message.reply_text(
                f"🚫 ታግደዋል። ለበለጠ መረጃ {ADMIN_USERNAME}"
            )
            return

        # ================= QUIZ START =================
        if cmd == "/stop2":

            for j in context.job_queue.get_jobs_by_name(str(chat.id)):
                j.schedule_removal()

            if chat.type == "private":
                async with db.execute(
                    "SELECT points FROM users WHERE user_id=?",
                    (user.id,)
                ) as c:
                    pts = (await c.fetchone())[0]

                await update.message.reply_text(
                    f"🛑 ቆሟል።\nነጥብዎ: {pts}"
                )
            else:
                async with db.execute(
                    "SELECT username, points FROM users ORDER BY points DESC LIMIT 15"
                ) as c:
                    rows = await c.fetchall()

                text = "📊 Best 15\n"
                for i, r in enumerate(rows, 1):
                    text += f"{i}. {r[0]} - {r[1]} pts\n"

                await update.message.reply_text(text)
            return

        subject_map = {
            "/history_srm2": "history",
            "/geography_srm2": "geography",
            "/mathematics_srm2": "mathematics",
            "/english_srm2": "english",
        }

        sub = subject_map.get(cmd)

        await update.message.reply_text(
            "🚀 ውድድር ጀመረ!\n8 ነጥብ | 4 ነጥብ | 1.5 ነጥብ"
        )

        context.job_queue.run_repeating(
            send_quiz,
            interval=180,
            first=1,
            chat_id=chat.id,
            data={"subject": sub},
            name=str(chat.id)
        )

# ===================== MAIN =====================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    app_bot = Application.builder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler(
        ["start2","history_srm2","geography_srm2",
         "mathematics_srm2","english_srm2","stop2"],
        start_handler
    ))

    app_bot.add_handler(PollAnswerHandler(receive_answer))

    keep_alive()
    app_bot.run_polling()

# 🔥 FIXED MAIN BUG
if __name__ == "__main__":
    main()
