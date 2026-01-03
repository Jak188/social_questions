import logging
import asyncio
import sqlite3
import json
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# --- CONFIGURATION ---
API_TOKEN = '8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE' # Render Environment Variable ላይ ካስገባህ os.getenv('BOT_TOKEN') ተጠቀም
ADMIN_IDS = [12345678]  # ያንተን የቴሌግራም ID እዚህ ይተኩ
QUIZ_INTERVAL = 240  # 4 ደቂቃ
DATABASE_NAME = "quiz_bot.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, score REAL DEFAULT 0, muted_until TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_state 
                 (chat_id INTEGER PRIMARY KEY, is_active INTEGER, subject TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- HELPER FUNCTIONS ---
def get_score(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    score = conn.execute("SELECT score FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return score[0] if score else 0

def update_score(user_id, username, points):
    conn = sqlite3.connect(DATABASE_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, score) VALUES (?, ?, 0)", (user_id, username))
    c.execute("UPDATE users SET score = score + ?, username = ? WHERE user_id = ?", (points, username, user_id))
    conn.commit()
    conn.close()

active_quizzes = {} # {chat_id: task}

# --- MIDDLEWARE FOR MUTED USERS ---
@dp.message_handler(lambda msg: True, content_types=types.ContentTypes.ANY)
async def check_mute(message: types.Message):
    conn = sqlite3.connect(DATABASE_NAME)
    user = conn.execute("SELECT muted_until FROM users WHERE user_id = ?", (message.from_id,)).fetchone()
    conn.close()
    
    if user and user[0]:
        until = datetime.fromisoformat(user[0])
        if datetime.now() < until:
            try: await message.delete() 
            except: pass
            return
    
    # ትዕዛዞችን ለማስተናገድ ወደ ቀጣዩ እንዲያልፍ ይፈቅዳል
    await dp.process_update(types.Update(message=message))

# --- QUIZ LOGIC ---
async def run_quiz(chat_id, subject):
    with open('questions.json', 'r', encoding='utf-8') as f:
        all_questions = json.load(f)
    
    questions = [q for q in all_questions if q.get('subject') == subject]
    if not questions:
        await bot.send_message(chat_id, "ለዚህ ትምህርት ጥያቄ አልተገኘም።")
        return

    while chat_id in active_quizzes:
        q = random.choice(questions)
        poll = await bot.send_poll(
            chat_id, q['q'], q['o'], 
            type='quiz', correct_option_id=q['c'], is_anonymous=False
        )
        
        # ለ 4 ደቂቃ መጠበቅ
        await asyncio.sleep(QUIZ_INTERVAL)
        
        # ማብራሪያ መላክ
        await bot.send_message(chat_id, f"💡 **ማብራሪያ፦**\n{q['exp']}", parse_mode="Markdown")

@dp.poll_answer_handler()
async def handle_poll_answer(quiz_answer: types.PollAnswer):
    # እዚህ ጋር ነጥብ አሰጣጥ (8, 4, 1.5) በሎጂክ ይጨመራል
    # ማሳሰቢያ፡ aiogram poll_answer ሰዓቱን ስለማይሰጥ ቀለል ባለ መንገድ ነጥብ ይያዛል
    update_score(quiz_answer.user.id, quiz_answer.user.full_name, 8) 
    await bot.send_message(quiz_answer.user.id, "🎉 ትክክል! 🚀 (ርችት)")

# --- COMMANDS ---
@dp.message_handler(commands=['start2'])
async def start_quiz(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    arg = message.get_args()
    if not arg:
        await message.reply("እባክህ የትምህርት አይነት ጥቀስ። ለምሳሌ: `History_srm`")
        return
    
    chat_id = message.chat.id
    if chat_id in active_quizzes: return
    
    task = asyncio.create_task(run_quiz(chat_id, arg.replace("_srm", "")))
    active_quizzes[chat_id] = task
    await message.answer(f"🌟 **{arg} ውድድር ተጀምሯል!** 🌟\nበየ 4 ደቂቃው ጥያቄ ይቀርባል።")

@dp.message_handler(commands=['stop2'])
async def stop_quiz(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    chat_id = message.chat.id
    if chat_id in active_quizzes:
        active_quizzes[chat_id].cancel()
        del active_quizzes[chat_id]
        
        # ውጤት ማሳያ (Rank 1-10)
        conn = sqlite3.connect(DATABASE_NAME)
        top = conn.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 10").fetchall()
        conn.close()
        
        res = "🏆 **የውድድሩ ውጤት** 🏆\n\n"
        for i, (name, score) in enumerate(top, 1):
            icon = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else "🔹"
            res += f"{icon} {i}. {name} - {score} ነጥብ\n"
        
        res += "\n✨ እንኳን ደስ አላችሁ! ✨"
        await message.answer(res)

@dp.message_handler(commands=['clear_rank2'])
async def clear_rank(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    conn = sqlite3.connect(DATABASE_NAME)
    conn.execute("UPDATE users SET score = 0")
    conn.commit()
    conn.close()
    await message.answer("♻️ ነጥብ በሙሉ ወደ 0 ተመልሷል።")

# --- MUTE LOGIC (17 MINUTES) ---
@dp.message_handler(lambda msg: msg.reply_to_message and not msg.text.startswith('/'))
async def admin_action(message: types.Message):
    if message.from_id in ADMIN_IDS: return # አድሚን አይታገድም
    
    # አድሚን ያልሆነ ሰው የአድሚን መልዕክት ከነካ
    if message.reply_to_message.from_id in ADMIN_IDS:
        until = datetime.now() + timedelta(minutes=17)
        conn = sqlite3.connect(DATABASE_NAME)
        conn.execute("UPDATE users SET muted_until = ? WHERE user_id = ?", (until.isoformat(), message.from_id))
        conn.commit()
        conn.close()
        await message.answer(f"⚠️ {message.from_user.full_name} የአድሚን ትዕዛዝ ስለነካህ ለ 17 ደቂቃ ታግደሃል!")

executor.start_polling(dp, skip_updates=True)
