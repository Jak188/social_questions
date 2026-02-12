import os, json, asyncio, random, re
 import aiosqlite
 from datetime import datetime, timedelta, timezone
 from flask import Flask
 from threading import Thread
 
 from telegram import Update, Poll
 from telegram.ext import (
     Application, CommandHandler, PollAnswerHandler,
     ContextTypes, ChatMemberHandler, filters, MessageHandler
 )
 
 # ===================== CONFIG =====================
 TOKEN = "8195013346:AAG0oJjZREWEhFVoaZGF4kxSwut1YKSw6lY"
 ADMIN_IDS = [7231324244, 8394878208]
 ADMIN_USERNAME = "@penguiner"
 GLOBAL_STOP = False
 
 # ===================== FLASK KEEP ALIVE =====================
 app = Flask(__name__)
 @app.route('/')
 def home(): return "Bot is Online!"
 
 def run(): app.run(host='0.0.0.0', port=8080)
 def keep_alive(): Thread(target=run, daemon=True).start()
 
 # ===================== DATABASE INIT =====================
 async def init_db():
     async with aiosqlite.connect("quiz_bot.db") as db:
         await db.execute("""CREATE TABLE IF NOT EXISTS users(
             user_id INTEGER PRIMARY KEY, username TEXT, points REAL DEFAULT 0,
             status TEXT DEFAULT 'pending', is_blocked INTEGER DEFAULT 0,
             muted_until TEXT, reg_at TEXT)""")
         await db.execute("""CREATE TABLE IF NOT EXISTS active_polls(
             poll_id TEXT PRIMARY KEY, correct_option INTEGER, chat_id INTEGER, first_winner INTEGER DEFAULT 0)""")
         await db.execute("""CREATE TABLE IF NOT EXISTS logs(
             user_id INTEGER, name TEXT, action TEXT, timestamp TEXT, date TEXT)""")
         await db.execute("""CREATE TABLE IF NOT EXISTS active_paths(
             chat_id INTEGER PRIMARY KEY, chat_title TEXT, starter_name TEXT, start_time TEXT)""")
         await db.commit()
 
 # ===================== BROADCAST UTIL =====================
 async def broadcast_to_all(context, text):
     async with aiosqlite.connect("quiz_bot.db") as db:
         async with db.execute("SELECT user_id FROM users") as c: users = await c.fetchall()
         async with db.execute("SELECT chat_id FROM active_paths") as c: groups = await c.fetchall()
     
     all_ids = {u[0] for u in users} | {g[0] for g in groups}
     for cid in all_ids:
         try:
             await context.bot.send_message(cid, f"{text}\n\nOwner: {ADMIN_USERNAME}", parse_mode="HTML")
             await asyncio.sleep(0.05)
         except: pass
 
 # ===================== QUIZ LOGIC =====================
 async def send_quiz(context: ContextTypes.DEFAULT_TYPE):
     if GLOBAL_STOP: return
     job = context.job
     try:
         with open("questions.json", "r", encoding="utf-8") as f: all_q = json.load(f)
         sub = job.data.get("subject")
         questions = [q for q in all_q if q.get("subject","").lower()==sub] if sub else all_q
         if not questions: return
         
         q = random.choice(questions)
         msg = await context.bot.send_poll(
             job.chat_id, f"📚 [{q.get('subject','General')}] {q['q']}", q["o"],
             type=Poll.QUIZ, is_anonymous=False, correct_option_id=int(q["c"]),
             explanation=q.get("exp","")
         )
         async with aiosqlite.connect("quiz_bot.db") as db:
             await db.execute("INSERT INTO active_polls VALUES(?,?,?,0)", (msg.poll.id, int(q["c"]), job.chat_id))
             await db.commit()
     except: pass
 
 async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
     ans = update.poll_answer
     async with aiosqlite.connect("quiz_bot.db") as db:
         async with db.execute("SELECT * FROM users WHERE user_id=?", (ans.user.id,)) as c: user = await c.fetchone()
         if not user or user[3] != "approved" or user[4] == 1: return
         if user[5] and datetime.now(timezone.utc) < datetime.fromisoformat(user[5]): return
 
         async with db.execute("SELECT correct_option, first_winner, chat_id FROM active_polls WHERE poll_id=?", (ans.poll_id,)) as c: poll = await c.fetchone()
         if not poll: return
 
         is_correct = ans.option_ids[0] == poll[0]
         # Points logic: First winner = 8, Correct = 4, Incorrect = 1.5
         if is_correct and poll[1] == 0:
             points = 8
             await db.execute("UPDATE active_polls SET first_winner=? WHERE poll_id=?", (ans.user.id, ans.poll_id))
             await context.bot.send_message(poll[2], f"🏆 <b>{ans.user.first_name}</b> ቀድሞ መልሶ 8 ነጥብ አግኝቷል!", parse_mode="HTML")
         else:
             points = 4 if is_correct else 1.5
 
         await db.execute("UPDATE users SET points = points + ? WHERE user_id=?", (points, ans.user.id))
         now = datetime.now()
         await db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (ans.user.id, ans.user.first_name, "✔️" if is_correct else "❎", now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d")))
         await db.commit()
 
 # ===================== HANDLERS =====================
 async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
     user = update.effective_user
     chat = update.effective_chat
     if not update.message: return
     cmd = update.message.text.split("@")[0].lower()
 
     if GLOBAL_STOP and user.id not in ADMIN_IDS:
         await update.message.reply_text(f"⛔️ ቦቱ በአድሚን ትእዛዝ ቆሟል።\nለበለጠ መረጃ {ADMIN_USERNAME}")
         return
 
     async with aiosqlite.connect("quiz_bot.db") as db:
         async with db.execute("SELECT * FROM users WHERE user_id=?", (user.id,)) as c: u = await c.fetchone()
 
         # Registration logic
         if not u:
             await db.execute("INSERT INTO users(user_id, username, reg_at) VALUES(?,?,?)", (user.id, user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
             await db.commit()
             await update.message.reply_text(f"👋 ውድ {user.first_name}\nምዝገባዎ በሂደት ላይ ነው። አድሚኑ እስኪቀበል ይጠብቁ።")
             for a in ADMIN_IDS: await context.bot.send_message(a, f"👤 New Reg: {user.first_name}\nID: <code>{user.id}</code>\n/approve reply", parse_mode="HTML")
             return
         
         if u[3] == "pending":
             await update.message.reply_text(f"⏳ ውድ {user.first_name} አድሚኑ busy ነው። ጥያቄዎ ሲረጋገጥ እናሳውቃለን።")
             return
 
         if u[4] == 1:
             await update.message.reply_text(f"🚫 ታግደዋል። መፍትሄ ለማግኘት {ADMIN_USERNAME} ን ያነጋግሩ።")
             return
 
         # Security: Private chat restricted commands
         allowed_priv = ["/start2","/history_srm2","/geography_srm2","/mathematics_srm2","/english_srm2","/rank2","/stop2"]
         if chat.type == "private" and cmd.startswith("/") and cmd not in allowed_priv and user.id not in ADMIN_IDS:
             await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user.id,))
             await db.commit()
             await update.message.reply_text(f"⚠️ የህግ ጥሰት! ታግደዋል። {ADMIN_USERNAME}")
             return
 
         # Security: Group chat restrictions (Mute/Point deduction)
         if chat.type != "private" and cmd.startswith("/") and cmd not in ["/start2","/stop2"] and user.id not in ADMIN_IDS:
             mute_time = (datetime.now(timezone.utc) + timedelta(minutes=17)).isoformat()
             await db.execute("UPDATE users SET points = points - 3.17, muted_until=? WHERE user_id=?", (mute_time, user.id))
             await db.commit()
             await update.message.reply_text(f"⚠️ {user.first_name} ህግ በመጣስዎ 3.17 ነጥብ ተቀንሷል + ለ17 ደቂቃ ታግደዋል።")
             for a in ADMIN_IDS: await context.bot.send_message(a, f"⚠️ Muted in Group: {user.first_name}\nID: <code>{user.id}</code>\n/unmute2 reply", parse_mode="HTML")
             return
 
         # Command Logic
         if cmd == "/stop2":
             for j in context.job_queue.get_jobs_by_name(str(chat.id)): j.schedule_removal()
             await db.execute("DELETE FROM active_paths WHERE chat_id=?", (chat.id,))
             await db.commit()
             res = "🛑 ውድድር ቆሟል።\n\n📊 Best 15:\n"
             async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 15") as c:
                 for i, r in enumerate(await c.fetchall(), 1): res += f"{i}. {r[0]} - {r[1]} pts\n"
             await update.message.reply_text(res)
             for a in ADMIN_IDS: await context.bot.send_message(a, f"🛑 Stop: {chat.title}\nBy: {user.first_name}")
             return
 
         if cmd in allowed_priv or cmd == "/start2":
             sub = {"/history_srm2":"history", "/geography_srm2":"geography", "/mathematics_srm2":"mathematics", "/english_srm2":"english"}.get(cmd)
             await update.message.reply_text("🚀 ውድድር ጀመረ! (በየ 3 ደቂቃ)\n8 ነጥብ | 4 ነጥብ | 1.5 ነጥብ")
             await db.execute("INSERT OR REPLACE INTO active_paths VALUES(?,?,?,?)", (chat.id, chat.title or "Private", user.first_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
             await db.commit()
             context.job_queue.run_repeating(send_quiz, interval=180, first=1, chat_id=chat.id, data={"subject": sub}, name=str(chat.id))
             for a in ADMIN_IDS: await context.bot.send_message(a, f"🚀 Start: {chat.title or 'Private'}\nBy: {user.first_name}\nTime: {datetime.now().strftime('%H:%M')}")
 
 # ===================== ADMIN CONTROLS =====================
 async def admin_ctrl(update: Update, context: ContextTypes.DEFAULT_TYPE):
     if update.effective_user.id not in ADMIN_IDS: return
     txt = update.message.text.split()
     cmd = txt[0][1:].lower()
     target_id = None
 
     if update.message.reply_to_message:
         match = re.search(r"ID: (\d+)|ID:<code>(\d+)</code>", update.message.reply_to_message.text)
         if match: target_id = int(match.group(1) or match.group(2))
     elif len(txt) > 1: target_id = int(txt[1])
 
     async with aiosqlite.connect("quiz_bot.db") as db:
         if cmd == "approve" and target_id:
             await db.execute("UPDATE users SET status='approved' WHERE user_id=?", (target_id,))
             await db.commit()
             try: await context.bot.send_message(target_id, f"✅ ምዝገባዎ ተቀባይነት አግኝቷል።\n{ADMIN_USERNAME}")
             except: pass
             await update.message.reply_text("Approved ✅")
 
         elif cmd == "anapprove" and target_id:
             await db.execute("DELETE FROM users WHERE user_id=?", (target_id,))
             await db.commit()
             try: await context.bot.send_message(target_id, "❌ ምዝገባዎ ውድቅ ሆኗል። ደግመው ይሞክሩ።")
             except: pass
             await update.message.reply_text("Rejected ❌")
 
         elif cmd == "block" and target_id:
             await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (target_id,))
             await db.commit()
             try: await context.bot.send_message(target_id, f"🚫 ታግደዋል። {ADMIN_USERNAME}")
             except: pass
             await update.message.reply_text("Blocked 🚫")
 
         elif cmd == "unmute2" and target_id:
             await db.execute("UPDATE users SET muted_until=NULL WHERE user_id=?", (target_id,))
             await db.commit()
             try: await context.bot.send_message(target_id, "✅ እገዳዎ ተነስቷል፤ በድጋሚ ላለመሳሳት ይሞክሩ።")
             except: pass
             await update.message.reply_text("Unmuted ✅")
 
         elif cmd == "oppt":
             global GLOBAL_STOP
             GLOBAL_STOP = True
             await broadcast_to_all(context, "⛔️ ቦቱ ከአድሚን በመጣ ትእዛዝ ቆሟል።")
 
         elif cmd == "opptt":
             GLOBAL_STOP = False
             await broadcast_to_all(context, "✅ ቦቱ ተመልሷል።")
 
         elif cmd == "log":
             async with db.execute("SELECT name, action, date, timestamp FROM logs ORDER BY rowid DESC LIMIT 230") as c:
                 res = "📜 Logs (Top 230)\n"
                 for r in await c.fetchall(): res += f"{r[0]} {r[1]} {r[2]} {r[3]}\n"
             await update.message.reply_text(res)
 
         elif cmd == "pin":
             async with db.execute("SELECT user_id, username FROM users") as c:
                 res = "👥 Users:\n"
                 for r in await c.fetchall(): res += f"ID: <code>{r[0]}</code> | {r[1]}\n"
             await update.message.reply_text(res, parse_mode="HTML")
 
 # ===================== NOTIFICATIONS =====================
 async def status_notif(update: Update, context: ContextTypes.DEFAULT_TYPE):
     m = update.my_chat_member
     status = "✅ አብርቷል" if m.new_chat_member.status == "member" else "❌ አጥፍቷል"
     for a in ADMIN_IDS: await context.bot.send_message(a, f"{status}\nBy: {update.effective_user.first_name} ({update.effective_user.id})")
 
 # ===================== MAIN =====================
 def main():
     loop = asyncio.new_event_loop()
     asyncio.set_event_loop(loop)
     loop.run_until_complete(init_db())
     keep_alive()
     
     app_bot = Application.builder().token(TOKEN).build()
     app_bot.add_handler(CommandHandler(["start2","history_srm2","geography_srm2","mathematics_srm2","english_srm2","stop2","rank2"], start_handler))
     app_bot.add_handler(CommandHandler(["approve","anapprove","block","unblock","unmute","unmute2","log","oppt","opptt","pin","gof","info"], admin_ctrl))
     app_bot.add_handler(PollAnswerHandler(receive_answer))
     app_bot.add_handler(ChatMemberHandler(status_notif, ChatMemberHandler.MY_CHAT_MEMBER))
     
     app_bot.run_polling()
 
 if __name__ == "__main__":
     main()
