.:
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

# --- Flask Server for Railway/Render 24/7 ---
server = Flask('')
@server.route('/')
def home(): return "Quiz Bot is Active!"
def run(): server.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
def keep_alive(): Thread(target=run).start()

# 1. ቦቱን እና አድሚኖችን መለየት (Rule 1)
API_TOKEN = '8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE'
ADMIN_IDS = [7231324244, 8394878208] 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# 3, 7. የዳታቤዝ ዝግጅት - ነጥብ ለመያዝ (Rule 3 & 7)
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

# --- Commands ---

@dp.message(Command("srm")) # 11. ውድድር መጀመሪያ (Rule 1, 6, 11)
async def cmd_srm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return 
    chat_id = message.chat.id
    if active_loops.get(chat_id): return await message.answer("⚠️ ውድድሩ ቀድሞውኑ እየሰራ ነው።")
    
    active_loops[chat_id] = True
    welcome_msg = (
        "🎯 የኩዊዝ ውድድር በደመቀ ሁኔታ ተጀመረ! 🎯\n\n"
        "🔥 ተወዳዳሪዎች ተዘጋጁ!\n"
        "🏆 አንደኛ ለሚመልስ: 8 ነጥብ\n"
        "✅ ለሌሎች ትክክለኛ መልሶች: 4 ነጥብ\n"
        "🎈 ለተሳትፎ ብቻ: 1.5 ነጥብ\n\n"
        "መልካም ዕድል! 🍀"
    )
    await message.answer(welcome_msg, parse_mode="Markdown")
    asyncio.create_task(quiz_timer(chat_id))

@dp.message(Command("stm")) # 5. ውድድር ማቆሚያ (Rule 5)
async def cmd_stm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    active_loops[message.chat.id] = False
    
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 1")
    winner = cursor.fetchone()
    if winner:
        congrats_text = (
            f"🛑 ውድድሩ ተጠናቋል! 🛑\n\n"
            f"🎊✨🎆 🎇 🎆 ✨🎊\n"
            f"🏆 የዛሬው ታላቅ አሸናፊ፦ {winner[0]}\n"
            f"💰 አጠቃላይ የሰበሰቡት ነጥብ፦ {winner[1]}\n"
            f"🎊✨🎆 🎇 🎆 ✨🎊\n\n"
            "እንኳን ደስ አሎት! 👏 ቀጣይ ውድድር እስከምንገናኝ ደህና ሰንብቱ!"
        )
        await message.answer(congrats_text, parse_mode="Markdown")
    else:
        await message.answer("🛑 ውድድሩ ቆሟል። ምንም ተመዝጋቢ የለም።")

@dp.message(Command("ru")) # Rank ማሳያ (Rule 6 - አድሚን ብቻ)
async def cmd_ru(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: 
        return await message.answer("❌ ይህ ትዕዛዝ ለአድሚኖች ብቻ የተፈቀደ ነው።")
    
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows: return await message.answer("እስካሁን ምንም ውጤት የለም።")
    text = "🏆 የደረጃ ሰንጠረዥ (Top 10) 🏆\n\n"
    for i, row in enumerate(rows, 1): text += f"{i}. {row[0]} — {row[1]} ነጥብ\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("crt")) # Rank ማጥፊያ (Rule 6 - አድሚን ብቻ)
async def cmd_crt(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    cursor.execute("DELETE FROM scores")
    conn.commit()
    await message.answer("🧹 የደረጃ ሰንጠረዥ በሙሉ ተሰርዟል!")

# --- Quiz Logic ---
async def quiz_timer(chat_id):
    all_q = load_questions()
    if not all_q: return
    available_questions = list(all_q)
    
    while active_loops.get(chat_id):
        if not available_questions: available_questions = list(all_q)
        
        q = random.choice(available_questions) # 12. Random Subject (Rule 12)
        available_questions.remove(q)
        
        try:
            sent_poll = await bot.send_poll(
                chat_id=chat_id,
                question=f"📚 Subject: {q.get('subject', 'General')}\n\n{q['q']}",
                options=q['o'],
                type='quiz',
                correct_option_id=q['c'],
                explanation=q.get('exp', ''),
                is_anonymous=False # ስም ለማወቅ (Rule 4)
            )
            poll_map[sent_poll.poll.id] = {"correct": q['c'], "chat_id": chat_id, "winners": []}
        except Exception as e: logging.error(f"Error: {e}")
        await asyncio.sleep(240) # 4 ደቂቃ ልዩነት

@dp.poll_answer()
async def on_poll_answer(poll_answer: types.PollAnswer):
    data = poll_map.get(poll_answer.poll_id)
    if not data: return
    
    user_id = poll_answer.user.id
    user_name = poll_answer.user.full_name
    
    # ትክክል ከሆነ
    if poll_answer.option_ids[0] == data["correct"]:
        is_first = len(data["winners"]) == 0
        data["winners"].append(user_id)
        
        # 8, 9. ነጥብ አሰጣጥ (Rule 8 & 9)
        points = 8 if is_first else 4
        save_score(user_id, user_name, points)
        
        # 4. ቀድሞ የመለሰውን ስም መናገር (Rule 4)
        if is_first:
            await bot.send_message(data["chat_id"], f"🚀 ፈጣኑ መላሽ!\n👏 {user_name} ቀድመህ በመመለስህ 8 ነጥብ አግኝተሃል! 🔥", parse_mode="Markdown")
    else:
        # 10. ለተሳተፈ 1.5 ነጥብ (Rule 10)
        save_score(user_id, user_name, 1.5)

async def main():
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if name == "main":
    asyncio.run(main())
