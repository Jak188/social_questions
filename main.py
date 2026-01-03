import asyncio
import json
import logging
import random
import sqlite3
import os
from datetime import timedelta, datetime
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# --- Flask Server ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- ቦት ዝግጅት ---
API_TOKEN = '8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE'
ADMIN_IDS = [7231324244, 8394878208] 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('quiz_results.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS scores (user_id INTEGER PRIMARY KEY, name TEXT, points REAL DEFAULT 0)')
conn.commit()

def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return []

active_loops = {}
poll_map = {}

def save_score(user_id, name, points):
    cursor.execute("SELECT points FROM scores WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        new_score = max(0, row[0] + points)
        cursor.execute("UPDATE scores SET points = ?, name = ? WHERE user_id = ?", (new_score, name, user_id))
    else:
        cursor.execute("INSERT INTO scores (user_id, name, points) VALUES (?, ?, ?)", (user_id, name, max(0, points)))
    conn.commit()

# --- Handlers ---

@dp.message(Command("start2"))
async def cmd_start2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    chat_id = message.chat.id
    active_loops[chat_id] = True
    await message.answer("🎯 አጠቃላይ ጥያቄዎች ተጀመሩ!")
    asyncio.create_task(quiz_timer(chat_id, None))

@dp.message(lambda message: message.text and "_srm" in message.text.lower())
async def cmd_subject_srm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    text = message.text.lower()
    # ሰብጀክቱን በትክክል መለየት
    subj = ""
    if "geography" in text: subj = "Geography"
    elif "history" in text: subj = "History"
    elif "english" in text: subj = "English"
    elif "maths" in text: subj = "Maths"
    
    chat_id = message.chat.id
    active_loops[chat_id] = True
    await message.answer(f"📚 የ **{subj}** ውድድር ተጀመረ!")
    asyncio.create_task(quiz_timer(chat_id, subj))

@dp.message(Command("stop2"))
async def cmd_stop2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    active_loops[message.chat.id] = False
    await message.answer("🛑 ውድድሩ ቆሟል::")

async def quiz_timer(chat_id, subj_filter):
    while active_loops.get(chat_id):
        all_q = load_questions()
        # እዚህ ጋር ነው ሰብጀክቱን የሚለየው
        if subj_filter:
            questions = [q for q in all_q if q.get('subject') == subj_filter]
        else:
            questions = all_q
            
        if not questions:
            await bot.send_message(chat_id, f"⚠️ ለ {subj_filter} የተዘጋጀ ጥያቄ አልተገኘም::")
            break
            
        q = random.choice(questions)
        sent_poll = await bot.send_poll(
            chat_id=chat_id,
            question=f"📚 {q.get('subject', 'General')}\n\n{q['q']}",
            options=q['o'], type='quiz', correct_option_id=q['c'],
            is_anonymous=False
        )
        poll_map[sent_poll.poll.id] = {"correct": q['c'], "chat_id": chat_id, "winners": []}
        await asyncio.sleep(240)

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    data = poll_map.get(poll_answer.poll_id)
    if not data: return
    if poll_answer.option_ids[0] == data["correct"]:
        is_first = len(data["winners"]) == 0
        data["winners"].append(poll_answer.user.id)
        save_score(poll_answer.user.id, poll_answer.user.full_name, 8 if is_first else 4)

async def main():
    keep_alive()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
