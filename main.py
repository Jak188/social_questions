import asyncio
import json
import logging
import random
import sqlite3
import os
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# --- Flask Server for Railway 24/7 ---
server = Flask('')
@server.route('/')
def home(): return "Quiz Bot is Active!"
def run(): server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
def keep_alive(): Thread(target=run).start()

# 1. ቦቱን እና አድሚኖችን መለየት
API_TOKEN = '8256328585:AAEZXXZrN608V2l4Hh_iK4ATPbACZFe-gC8'
ADMIN_IDS = [7231324244, 8394878208] 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# 2. የዳታቤዝ ዝግጅት (ነጥብ ለመቆጠብ)
conn = sqlite3.connect('quiz_results.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS scores 
                  (user_id INTEGER PRIMARY KEY, name TEXT, points REAL DEFAULT 0)''')
conn.commit()

# 3. የጥያቄዎች ፋይል ማንበብ
def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return []

active_loops = {}
poll_map = {}

def save_score(user_id, name, points):
    cursor.execute("SELECT points FROM scores WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        new_score = row[0] + points
        cursor.execute("UPDATE scores SET points = ?, name = ? WHERE user_id = ?", (new_score, name, user_id))
    else:
        cursor.execute("INSERT INTO scores (user_id, name, points) VALUES (?, ?, ?)", (user_id, name, points))
    conn.commit()

# --- Custom Commands ---

@dp.message(Command("srm")) # 1. ውድድር መጀመሪያ
async def cmd_srm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return # 6. ለአድሚን ብቻ
    chat_id = message.chat.id
    if active_loops.get(chat_id): return await message.answer("⚠️ ውድድሩ ቀድሞውኑ እየሰራ ነው።")
    
    active_loops[chat_id] = True
    await message.answer("🎯 የኩዊዝ ውድድር ተጀመረ! መልካም ዕድል! 🍀")
    asyncio.create_task(quiz_timer(chat_id))

@dp.message(Command("stm")) # 2 & 7. ውድድር ማቆሚያ እና አሸናፊ ማሳወቂያ
async def cmd_stm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    active_loops[message.chat.id] = False
    
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 1")
    winner = cursor.fetchone()
    if winner:
        congrats_text = (
            f"🛑 ውድድሩ ተጠናቋል! 🛑\n\n"
            f"🎊✨🎆 🎇 🎆 ✨🎊\n"
            f"🏆 የዛሬው ታላቅ አሸናፊ፡ {winner[0]}\n"
            f"💰 አጠቃላይ ነጥብ፡ {winner[1]}\n"
            f"🎊✨🎆 🎇 🎆 ✨🎊\n\n"
            "እንኳን ደስ አሎት! 👏"
        )
        await message.answer(congrats_text)
    else:
        await message.answer("🛑 ውድድሩ ቆሟል።")

@dp.message(Command("ru")) # 3. ደረጃ ለማየት
async def cmd_ru(message: types.Message):
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows: return await message.answer("እስካሁን ምንም ውጤት የለም።")
    text = "🏆 የደረጃ ሰንጠረዥ 🏆\n\n"
    for i, row in enumerate(rows, 1): text += f"{i}. {row[0]} — {row[1]} ነጥብ\n"
    await message.answer(text)

@dp.message(Command("crt")) # 4. Rank clear ማድረጊያ
async def cmd_crt(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    cursor.execute("DELETE FROM scores")
    conn.commit()
    await message.answer("🧹 የደረጃ ሰንጠረዥ ተሰርዟል! በአዲስ ይጀመራል።")

# --- 10 & 11. Random & No Repeat Loop ---
async def quiz_timer(chat_id):
    all_q = load_questions()
    available_questions = list(all_q)
    
    while active_loops.get(chat_id):
        if not available_questions: available_questions = list(all_q) # ካለቁ እንደገና
        
        q = random.choice(available_questions) # 10. Random
        available_questions.remove(q) # 11. እንዳይደገም
        
        try:
            sent_poll = await bot.send_poll(
                chat_id=chat_id,
                question=f"📚 Subject: {q.get('subject', 'General')}\n\n{q['q']}",
                options=q['o'],
                type='quiz',
                correct_option_id=q['c'],
                explanation=q.get('exp', ''),
                is_anonymous=False
            )
            poll_map[sent_poll.poll.id] = {"correct": q['c'], "chat_id": chat_id, "winners": []}
        except Exception as e: logging.error(f"Error: {e}")
        await asyncio.sleep(240) # 4 ደቂቃ

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    data = poll_map.get(poll_answer.poll_id)
    if not data: return
    
    user_id = poll_answer.user.id
    user_name = poll_answer.user.full_name
    
    if poll_answer.option_ids[0] == data["correct"]:
        data["winners"].append(user_id)
        is_first = len(data["winners"]) == 1
        points = 8 if is_first else 4
        save_score(user_id, user_name, points) # 9. Save score
        
        # 5 & 12. ቀድሞ ለመለሰ ሰው GP ላይ ማሳወቅ
        if is_first:
            await bot.send_message(data["chat_id"], f"👏 ብርቱ ነህ {user_name}! ቀድመህ በመመለስህ 8 ነጥብ አግኝተሃል! 🎊")
    else:
        save_score(user_id, user_name, 1.5)

async def main():
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
