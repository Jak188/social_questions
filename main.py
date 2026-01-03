import logging
import asyncio
import sqlite3
import json
import random
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# --- CONFIGURATION ---
API_TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_IDS = [748551720] 
QUIZ_INTERVAL = 240 # ህግ 1: 4 ደቂቃ

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- DATABASE (ህግ 17) ---
def init_db():
    conn = sqlite3.connect("quiz.db")
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, score REAL DEFAULT 0, muted_until TEXT)")
    conn.commit()
    conn.close()

init_db()

# --- MUTE LOGIC (ህግ 7, 8, 9) ---
@dp.message_handler(lambda m: m.reply_to_message and m.reply_to_message.from_id in ADMIN_IDS)
async def handle_mute(message: types.Message):
    if message.from_id in ADMIN_IDS: return
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    conn = sqlite3.connect("quiz.db")
    conn.execute("INSERT OR REPLACE INTO users (id, name, muted_until) VALUES (?, ?, ?)", 
                 (message.from_id, message.from_user.full_name, until))
    conn.commit()
    conn.close()
    await message.delete()
    await message.answer(f"⚠️ {message.from_user.full_name} አድሚን ስለነካህ ለ 17 ደቂቃ ታግደሃል!")

# --- QUIZ ENGINE (ህግ 14, 15, 16) ---
active_quizzes = {}

async def run_quiz(chat_id, subject):
    with open('questions.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    questions = [q for q in data if q.get('subject', '').lower() == subject.lower()]
    
    await bot.send_message(chat_id, f"🌟 የ {subject} ውድድር ተጀመረ! 🌟 (ህግ 13)")
    
    while chat_id in active_quizzes:
        q = random.choice(questions)
        poll = await bot.send_poll(
            chat_id, q['q'], q['o'], type='quiz', 
            correct_option_id=q['c'], is_anonymous=False,
            explanation=q.get('exp', "ትክክለኛ መልስ!") # ህግ 14: ማብራሪያ
        )
        await asyncio.sleep(QUIZ_INTERVAL)

# --- COMMANDS ---
@dp.message_handler(commands=['start2'])
async def start_quiz(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    subj = message.get_args() or "History"
    task = asyncio.create_task(run_quiz(message.chat.id, subj))
    active_quizzes[message.chat.id] = task

@dp.message_handler(commands=['stop2']) # ህግ 5, 12: የዋንጫ ሽልማት
async def stop_quiz(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    if message.chat.id in active_quizzes:
        active_quizzes[message.chat.id].cancel()
        del active_quizzes[message.chat.id]
        
        conn = sqlite3.connect("quiz.db")
        top = conn.execute("SELECT name, score FROM users ORDER BY score DESC LIMIT 10").fetchall()
        conn.close()
        
        res = "🏆 **የውድድሩ ውጤት** 🏆\n\n"
        icons = ["🥇", "🥈", "🥉"] + ["🏅"]*7
        for i, (name, score) in enumerate(top):
            res += f"{icons[i]} {i+1}ኛ. {name or 'ተወዳዳሪ'} - {score} ነጥብ\n"
        await message.answer(res + "\n🎇 እንኳን ደስ አላችሁ! 🎇")

@dp.message_handler(commands=['clear_rank2']) # ህግ 10
async def clear_rank(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    conn = sqlite3.connect("quiz.db")
    conn.execute("UPDATE users SET score = 0")
    conn.commit()
    conn.close()
    await message.answer("♻️ ነጥብ ተሰርዟል!")

# --- SCORE HANDLING (ህግ 2, 3, 4, 6) ---
@dp.poll_answer_handler()
async def poll_ans(ans: types.PollAnswer):
    # ነጥብ አሰጣጥ 8, 4, 1.5 ሎጂክ እዚህ ይጨመራል
    conn = sqlite3.connect("quiz.db")
    conn.execute("UPDATE users SET score = score + 8 WHERE id = ?", (ans.user.id,))
    conn.commit()
    conn.close()
    await bot.send_message(ans.user.id, "🎯 ትክክል! 🎇 (ህግ 6)")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
