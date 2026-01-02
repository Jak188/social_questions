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

# --- Flask Server (ለ Koyeb/Render ጤንነት ማረጋገጫ) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    # Koyeb የሚሰጠውን PORT ይጠቀማል
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- የቦት ዝግጅት ---
API_TOKEN = '8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE'
ADMIN_IDS = [7231324244, 8394878208] 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# የዳታቤዝ ግንኙነት
conn = sqlite3.connect('quiz_results.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS scores 
                  (user_id INTEGER PRIMARY KEY, name TEXT, points REAL DEFAULT 0)''')
conn.commit()

def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading questions: {e}")
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

async def punish_user(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    save_score(user_id, user_name, -3)
    until_date = datetime.now() + timedelta(minutes=17)
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id, user_id=user_id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.answer(f"🚫 **{user_name}** የአድሚን ትዕዛዝ በመንካትህ ለ 17 ደቂቃ ታግደሃል!")
    except:
        pass

# --- ትዕዛዞች (Handlers) ---

@dp.message(Command("start2"))
async def cmd_start2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    chat_id = message.chat.id
    if active_loops.get(chat_id): return
    active_loops[chat_id] = True
    await message.answer("🎯 የኩዊዝ ውድድር በደመቀ ሁኔታ ተጀመረ! 🍀")
    asyncio.create_task(quiz_timer(chat_id, None))

@dp.message(lambda message: message.text and any(subj in message.text.lower() for subj in ["geography_srm", "history_srm", "english_srm", "maths_srm"]))
async def cmd_subject_srm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    text = message.text.lower()
    subj = "Geography" if "geography" in text else "History" if "history" in text else "English" if "english" in text else "Maths"
    chat_id = message.chat.id
    if active_loops.get(chat_id): return
    active_loops[chat_id] = True
    await message.answer(f"📚 የ **{subj}** ውድድር ተጀመረ! መልካም ዕድል! 🍀")
    asyncio.create_task(quiz_timer(chat_id, subj))

@dp.message(Command("stop2"))
async def cmd_stop2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    active_loops[message.chat.id] = False
    await message.answer("🛑 ውድድሩ በይፋ ቆሟል::")

async def quiz_timer(chat_id, subj_filter):
    all_q = load_questions()
    questions = [q for q in all_q if q.get('subject') == subj_filter] if subj_filter else all_q
    if not questions: return
    
    while active_loops.get(chat_id):
        q = random.choice(questions)
        try:
            sent_poll = await bot.send_poll(
                chat_id=chat_id,
                question=f"📚 {q.get('subject', 'General')}\n\n{q['q']}",
                options=q['o'], type='quiz', correct_option_id=q['c'],
                explanation=q.get('exp', ''),
                is_anonymous=False
            )
            poll_map[sent_poll.poll.id] = {"correct": q['c'], "chat_id": chat_id, "winners": []}
        except Exception as e:
            logging.error(f"Error sending poll: {e}")
        await asyncio.sleep(240)

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    data = poll_map.get(poll_answer.poll_id)
    if not data: return
    user_id = poll_answer.user.id
    user_name = poll_answer.user.full_name
    chat_id = data["chat_id"]

    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ["restricted", "kicked", "left"] and not member.can_send_messages:
            return 
    except:
        pass

    if poll_answer.option_ids[0] == data["correct"]:
        is_first = len(data["winners"]) == 0
        data["winners"].append(user_id)
        save_score(user_id, user_name, 8 if is_first else 4)
        if is_first:
            await bot.send_message(chat_id, f"🚀 **ፈጣኑ መላሽ!**\n👏 {user_name} 8 ነጥብ አግኝተሃል! 🔥")
    else:
        save_score(user_id, user_name, 1.5)

async def main():
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
