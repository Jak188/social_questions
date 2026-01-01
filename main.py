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

# --- Flask Server (ለ 24/7 ስራ) ---
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

# 2. የዳታቤዝ ዝግጅት
conn = sqlite3.connect('quiz_results.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS scores 
                  (user_id INTEGER PRIMARY KEY, name TEXT, points REAL DEFAULT 0)''')
conn.commit()

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

# --- የቅጣት ተግባር (17 ደቂቃ Mute) ---
async def punish_user(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    until_date = datetime.now() + timedelta(minutes=17) # 1. እገዳው ለ 17 ደቂቃ
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.answer(f"🚫 **የቅጣት እርምጃ!**\n\n{user_name} የአድሚን ትዕዛዝ በመንካትህ ለ **17 ደቂቃ** ታግደሃል።")
    except: pass

# --- Commands ---

@dp.message(Command("start")) # 3. ውድድር መጀመሪያ
async def cmd_start(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    chat_id = message.chat.id
    if active_loops.get(chat_id): return
    active_loops[chat_id] = True
    await message.answer("🎯 **የኩዊዝ ውድድር በደመቀ ሁኔታ ተጀመረ!**\n\nመልካም ዕድል ለሁላችሁም! 🍀")
    asyncio.create_task(quiz_timer(chat_id))

@dp.message(Command("stop")) # 4. ውድድር ማቆሚያ
async def cmd_stop(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    active_loops[message.chat.id] = False
    
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    winners = cursor.fetchall()
    
    if winners:
        text = "🛑 **ውድድሩ ተጠናቋል! የደረጃ ውጤት፦**\n\n"
        for i, row in enumerate(winners, 1):
            medal = ""
            if i == 1: medal = "🥇 🏆🏆🏆 (የወርቅ ዋንጫ)" # 10. ሽልማት
            elif i == 2: medal = "🥈 🏆🏆 (የብር ዋንጫ)"
            elif i == 3: medal = "🥉 🏆 (የነሀስ ሜዳሊያ)"
            else: medal = "👤"
            text += f"{i}. {row[0]} — {row[1]} ነጥብ {medal}\n"
        
        # 8 & 9. የማበረታቻ መልዕክት እና ርችት
        text += "\n🎊✨🎆 🎇 🎆 ✨🎊\n"
        text += "እንኳን ደስ አላችሁ! 👏 በቅጣይ ከ1-10 ስማችሁ በደረጃ እንዲነሳ በትጋት ተሳተፉ!"
        await message.answer(text)
    else:
        await message.answer("🛑 ውድድሩ ቆሟል። ምንም ውጤት የለም።")

@dp.message(Command("rank")) # 5. ውጤት ለማየት
async def cmd_rank(message: types.Message):
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows: return await message.answer("እስካሁን ምንም ውጤት የለም።")
    text = "🏆 **አጠቃላይ የደረጃ ሰንጠረዥ** 🏆\n\n"
    for i, row in enumerate(rows, 1): text += f"{i}. {row[0]} — {row[1]} ነጥብ\n"
    await message.answer(text)

@dp.message(Command("clear_rank")) # 6. ውጤት ማጥፊያ
async def cmd_clear(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    cursor.execute("DELETE FROM scores")
    conn.commit()
    await message.answer("🧹 የደረጃ ሰንጠረዥ በሙሉ ተሰርዟል!")

@dp.message(Command("un_mute")) # 1. እገዳ ማንሻ (ሪፕላይ)
async def cmd_unmute(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.reply_to_message: return await message.answer("እባክዎ Reply ያድርጉ።")
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=message.reply_to_message.from_user.id,
            permissions=types.ChatPermissions(can_send_messages=True, can_send_polls=True)
        )
        await message.answer(f"✅ የ {message.reply_to_message.from_user.full_name} እገዳ ተነስቷል።")
    except: pass

# --- ኩዊዝ ታይመር ---
async def quiz_timer(chat_id):
    all_q = load_questions()
    if not all_q: return
    available = list(all_q)
    while active_loops.get(chat_id):
        if not available: available = list(all_q)
        q = random.choice(available)
        available.remove(q)
        try:
            sent_poll = await bot.send_poll(
                chat_id=chat_id,
                question=f"📚 Subject: {q.get('subject', 'General')}\n\n{q['q']}",
                options=q['o'], type='quiz', correct_option_id=q['c'], is_anonymous=False
            )
            poll_map[sent_poll.poll.id] = {"correct": q['c'], "chat_id": chat_id, "winners": []}
        except: pass
        await asyncio.sleep(240)

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    data = poll_map.get(poll_answer.poll_id)
    if not data: return
    user_id = poll_answer.user.id
    user_name = poll_answer.user.full_name
    
    if poll_answer.option_ids[0] == data["correct"]:
        is_first = len(data["winners"]) == 0
        data["winners"].append(user_id)
        save_score(user_id, user_name, 8 if is_first else 4)
        if is_first: # 7. ለፈጣን መላሽ ርችት
            await bot.send_message(data["chat_id"], f"🚀 **ፈጣን መላሽ!**\n👏 {user_name} በትክክል መልሰሃል! 🎆🎇")
    else:
        save_score(user_id, user_name, 1.5)

async def main():
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
