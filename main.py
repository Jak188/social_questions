import logging
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# --- CONFIG ---
API_TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_IDS = [748551720] # ያንተ ID
QUIZ_INTERVAL = 240 # 4 ደቂቃ (ህግ 1)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect("quiz.db")
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, score REAL DEFAULT 0, muted_until TEXT)")
    conn.commit()
    conn.close()

init_db()

# --- ADMIN RULE (ህግ 7) ---
@dp.message_handler(lambda m: m.reply_to_message and m.reply_to_message.from_id in ADMIN_IDS)
async def admin_rule(message: types.Message):
    if message.from_id in ADMIN_IDS: return
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    conn = sqlite3.connect("quiz.db")
    conn.execute("INSERT OR REPLACE INTO users (id, muted_until) VALUES (?, ?)", (message.from_id, until))
    conn.commit()
    conn.close()
    await message.delete()
    await message.answer(f"⚠️ {message.from_user.full_name} አድሚን ስለነካህ ለ 17 ደቂቃ ታግደሃል!")

# --- COMMANDS ---
@dp.message_handler(commands=['start2'])
async def start_cmd(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    await message.answer("🚀 ውድድሩ ተጀመረ! (ህግ 13)")

@dp.message_handler(commands=['stop2'])
async def stop_cmd(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    await message.answer("🏆 የውድድሩ ውጤት... 🎇 (ህግ 5)")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
