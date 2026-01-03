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
# Render Environment Variables ውስጥ BOT_TOKEN መኖሩን አረጋግጥ
API_TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_IDS = [748551720]  # ያንተን ID እዚህ ያስገባሁት ነው
QUIZ_INTERVAL = 240  # 4 ደቂቃ (ህግ 1)
DATABASE_NAME = "quiz_data.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- DATABASE SETUP (ህግ 17) ---
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, score REAL DEFAULT 0, muted_until TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# --- MUTE LOGIC (ህግ 7, 8, 9) ---
@dp.message_handler(lambda m: m.reply_to_message and m.reply_to_message.from_id in ADMIN_IDS)
async def handle_admin_reply(message: types.Message):
    if message.from_id in ADMIN_IDS: return
    
    until = datetime.now() + timedelta(minutes=17)
    conn = sqlite3.connect(DATABASE_NAME)
    conn.execute("INSERT OR REPLACE INTO users (id, name, muted_until) VALUES (?, ?, ?)", 
                 (message.from_id, message.from_user.full_name, until.isoformat()))
    conn.commit()
    conn.close()
    
    await message.delete()
    await message.answer(f"⚠️ {message.from_user.full_name} የአድሚን ትዕዛዝ ስለነካህ ለ 17 ደቂቃ ታግደሃል! (ህግ 7)")

# --- QUIZ LOGIC ---
active_games = {}

@dp.message_handler(commands=['start2'])
async def cmd_start(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    subj = message.get_args() or "General"
    await message.answer(f"🚀 የ {subj} ውድድር ተጀመረ! በየ 4 ደቂቃው ጥያቄ ይወጣል (ህግ 13)።")
    # እዚህ ጋር ጥያቄ የመላክ loop ይጨምራል

@dp.message_handler(commands=['stop2']) # ህግ 5, 12
async def cmd_stop(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    conn = sqlite3.connect(DATABASE_NAME)
    top = conn.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 10").fetchall()
    conn.close()
    
    res = "🏆 **የውድድሩ ውጤት (Rank 1-10)** 🏆\n\n"
    icons = ["🥇", "🥈", "🥉"] + ["🏅"]*7
    for i, (name, score) in enumerate(top):
        res += f"{icons[i]} {i+1}. {name} - {score} ነጥብ\n"
    
    await message.answer(res + "\n🎇 እንኳን ደስ አላችሁ! 🎇 (ህግ 5)")

@dp.message_handler(commands=['clear_rank2']) # ህግ 10
async def cmd_clear(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    conn = sqlite3.connect(DATABASE_NAME)
    conn.execute("UPDATE users SET score = 0")
    conn.commit()
    conn.close()
    await message.answer("♻️ ነጥብ ተሰርዟል (ህግ 10)።")

# --- SCORE HANDLING (ህግ 2, 3, 4, 6) ---
@dp.poll_answer_handler()
async def handle_poll(quiz_answer: types.PollAnswer):
    # ለትክክል መልስ 8 ነጥብ (ህግ 2)
    # ለዘገየ 4 ነጥብ (ህግ 3)
    # ለተሳተፈ 1.5 ነጥብ (ህግ 4)
    # ሎጂኩ እዚህ ጋር ነጥቡን በ SQL update ያደርጋል
    pass

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
