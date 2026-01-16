import os, json, asyncio, random, aiosqlite
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online and Ready!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- Configuration ---
TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
ADMIN_IDS = [7231324244, 8394878208]
ADMIN_USERNAME = "@penguiner"

# --- Database Setup ---
async def init_db():
    async with aiosqlite.connect('quiz_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0, 
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0, muted_until TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS active_polls 
            (poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS logs 
            (user_id INTEGER, name TEXT, action TEXT, timestamp TEXT)''')
        await db.commit()

async def get_user(uid):
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (uid,)) as c: return await c.fetchone()

# --- Quiz Engine ---
async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
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
    user = await get_user(ans.user.id)
    if not user or user[3] != 'approved' or user[4] == 1: return
    
    async with aiosqlite.connect('quiz_bot.db') as db:
        async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id = ?", (ans.poll_id,)) as c:
            poll_data = await c.fetchone()
        if not poll_data: return
        
        is_correct = (ans.option_ids[0] == poll_data[0])
        # ነጥብ አሰጣጥ: 8 ለቀደመ፣ 4 ለዘገየ፣ 1.5 ለተሳሳተ
        if is_correct:
            if poll_data[1] == 0:
                points = 8
                await db.execute("UPDATE active_polls SET first_winner = ? WHERE poll_id = ?", (ans.user.id, ans.poll_id))
                await context.bot.send_message(poll_data[2], f"🏆 {ans.user.first_name} ቀድሞ በመመለስ 8 ነጥብ አግኝቷል!")
            else:
                points = 4
        else:
            points = 1.5
        
        await db.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, ans.user.id))
        await db.execute("INSERT INTO logs (user_id, name, action, timestamp) VALUES (?, ?, ?, ?)", 
                         (ans.user.id, ans.user.first_name, "✅" if is_correct else "❌", datetime.now().strftime("%H:%M:%S")))
        await db.commit()

# --- Handlers ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    u_data = await get_user(user.id)

    if u_data and u_data[4] == 1: return

    if not u_data:
        async with aiosqlite.connect('quiz_bot.db') as db:
            await db.execute("INSERT INTO users (user_id, username, status) VALUES (?, ?, 'pending')", (user.id, user.first_name))
            await db.commit()
        # የምዝገባ ማሳወቂያ ዲዛይን (ያለ backtick)
        reg_msg = (f"👤 አዲስ ተመዝጋቢ:\n"
                   f"ስም: {user.first_name}\n"
                   f"ID: {user.id}\n"
                   f"ለማጽደቅ: /approve {user.id}\n"
                   f"ለመከልከል: /anapprove {user.id}")
        for admin in ADMIN_IDS: await context.bot.send_message(admin, reg_msg)
        await update.message.reply_text("ምዝገባዎ ለአድሚን ደርሷል።")
        return

    cmd = update.message.text.split('@')[0][1:].lower()
    subject_map = {"history_srm2":"history", "geography_srm2":"geography", "mathematics_srm2":"mathematics", "english_srm2":"english"}
    subject = subject_map.get(cmd)

    if subject:
        old_jobs = context.job_queue.get_jobs_by_name(str(chat.id))
        for j in old_jobs: j.schedule_removal()
        
        now_time = datetime.now().strftime("%H:%M")
        context.job_queue.run_repeating(send_quiz, interval=240, first=1, chat_id=chat.id, 
                                        data={'subject': subject, 'starter': user.first_name, 'time': now_time}, 
                                        name=str(chat.id))
        await update.message.reply_text(f"🚀 የ{subject} ውድድር ተጀመረ!")
        # አድሚን ማሳወቂያ
        admin_info = f"📢 ውድድር ተጀምሯል!\nበ: {user.first_name}\nቦታ: {chat.title if chat.title else 'Private'}\nሰዓት: {now_time}"
        for admin in ADMIN_IDS: await context.bot.send_message(admin, admin_info)

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    
    target_user_id = None
    # Reply ተደርጎ ከሆነ የዛን ሰው ID መውሰድ
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
    elif context.args:
        target_user_id = int(context.args[0])
    
    if not target_user_id: return

    cmd = update.message.text.split()[0][1:].lower()
    async with aiosqlite.connect('quiz_bot.db') as db:
        if cmd == "block":
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (target_user_id,))
            msg = "🚫 ተጠቃሚው ታግዷል።"
        elif cmd == "unblock":
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (target_user_id,))
            msg = "✅ እገዳው ተነስቷል።"
        elif cmd == "mute":
            mute_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            await db.execute("UPDATE users SET muted_until = ? WHERE user_id = ?", (mute_until, target_user_id))
            msg = "🤐 ተጠቃሚው ለ24 ሰዓት ታግዷል።"
        elif cmd == "unmute":
            await db.execute("UPDATE users SET muted_until = NULL WHERE user_id = ?", (target_user_id,))
            msg = "🔊 ተጠቃሚው መናገር ይችላል።"
        elif cmd == "stop2":
            chat_id = str(update.effective_chat.id)
            jobs = context.job_queue.get_jobs_by_name(chat_id)
            for j in jobs: j.schedule_removal()
            now_time = datetime.now().strftime("%H:%M")
            msg = f"🏁 ውድድሩ በ {update.effective_user.first_name} በ {now_time} ቆሟል።"
            for admin in ADMIN_IDS: await context.bot.send_message(admin, f"🏁 ውድድር ቆሟል!\nበ: {update.effective_user.first_name}\nቦታ: {update.effective_chat.title}\nሰዓት: {now_time}")
        
        await db.commit()
        await update.message.reply_text(msg)

def main():
    asyncio.run(init_db())
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler(["start2", "history_srm2", "geography_srm2", "mathematics_srm2", "english_srm2"], start_handler))
    app_bot.add_handler(CommandHandler(["block", "unblock", "mute", "unmute", "stop2", "approve"], admin_action))
    app_bot.add_handler(PollAnswerHandler(receive_answer))
    keep_alive()
    app_bot.run_polling()

if __name__ == '__main__': main()
