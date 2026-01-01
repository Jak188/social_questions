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

# የዳታቤዝ ዝግጅት
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
    until_date = datetime.now() + timedelta(minutes=17) # 17 ደቂቃ እገዳ
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.answer(f"🚫 **የቅጣት እርምጃ!**\n\n{user_name} የአድሚን ትዕዛዝ በመንካትህ ለ **17 ደቂቃ** ታግደሃል።")
    except: pass

# --- Commands (ቁጥር 2 የታከለባቸው) ---

@dp.message(Command("start2")) # 3. ውድድር መጀመሪያ
async def cmd_start2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    chat_id = message.chat.id
    if active_loops.get(chat_id): return
    active_loops[chat_id] = True
    await message.answer("🎯 **የኩዊዝ ውድድር በደመቀ ሁኔታ ተጀመረ!**\n\nመልካም ዕድል ለሁላችሁም! 🍀", parse_mode="Markdown")
    asyncio.create_task(quiz_timer(chat_id))

@dp.message(Command("stop2")) # 4, 8, 9, 10. ውድድር ማቆሚያ እና ሽልማት
async def cmd_stop2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    active_loops[message.chat.id] = False
    
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    winners = cursor.fetchall()
    
    if winners:
        text = "🛑 **ውድድሩ ተጠናቋል!** 🛑\n\n"
        medals = {0: "🥇 🏆🏆🏆 (3 የወርቅ ዋንጫ)", 1: "🥈 🏆🏆 (2 የብር ዋንጫ)", 2: "🥉 🏆 (1 የነሐስ ሜዳሊያ)"}
        
        for i, row in enumerate(winners):
            award = medals.get(i, "🎖")
            text += f"{i+1}. {row[0]} — {row[1]} ነጥብ {award}\n"
        
        text += "\n🎊✨🎆 🎇 🎆 ✨🎊\n"
        text += "እንኳን ደስ አላችሁ! ቀጣይ ከ 1-10 ስማችሁ በደረጃ እንዲመጣ በትጋት ተሳተፉ። 👏"
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("🛑 ውድድሩ ቆሟል። ምንም ውጤት የለም።")

@dp.message(Command("rank2")) # 5. ውጤት ለማየት
async def cmd_rank2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows: return await message.answer("እስካሁን ምንም ውጤት የለም።")
    text = "🏆 **የደረጃ ሰንጠረዥ (Top 10)** 🏆\n\n"
    for i, row in enumerate(rows, 1): text += f"{i}. {row[0]} — {row[1]} ነጥብ\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("clear_rank2")) # 6. ውጤት ማጥፊያ
async def cmd_clear2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return await punish_user(message)
    cursor.execute("DELETE FROM scores")
    conn.commit()
    await message.answer("🧹 የደረጃ ሰንጠረዥ በሙሉ ተሰርዟል!")

@dp.message(Command("un_mute2")) # 1. እገዳ ማንሻ (በሪፕላይ)
async def cmd_unmute2(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    if not message.reply_to_message: return await message.answer("⚠️ Reply በማድረግ ይጠቀሙ።")
    target_user = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id, user_id=target_user.id,
            permissions=types.ChatPermissions(can_send_messages=True, can_send_polls=True, can_send_other_messages=True)
        )
        await message.answer(f"✅ የ {target_user.full_name} እገዳ ተነስቷል።")
    except: pass

# --- ኩዊዝ ታይመር ---
async def quiz_timer(chat_id):
    all_q = load_questions()
    if not all_q: return
    available_questions = list(all_q)
    while active_loops.get(chat_id):
        if not available_questions: available_questions = list(all_q)
        q = random.choice(available_questions)
        available_questions.remove(q)
        try:
            await bot.send_poll(
                chat_id=chat_id, question=f"📚 {q['q']}", options=q['o'],
                type='quiz', correct_option_id=q['c'], is_anonymous=False
            )
        except: pass
        await asyncio.sleep(240)

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    # (የነጥብ አሰጣጥ ሎጂክ እዚህ ጋር ይቀጥላል...)
    pass

async def main():
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
