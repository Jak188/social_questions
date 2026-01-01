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

# --- Flask Server for 24/7 ---
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

# ዳታቤዝ
conn = sqlite3.connect('quiz_results.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS scores 
                  (user_id INTEGER PRIMARY KEY, name TEXT, points REAL DEFAULT 0)''')
conn.commit()

active_loops = {}
poll_map = {}

# --- የቅጣት ተግባር (Mute for 13 Minutes) ---
async def punish_user(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    chat_id = message.chat.id
    
    # ተራ ተጠቃሚ አድሚን ትዕዛዝ ቢሞክር ለ 13 ደቂቃ Mute ይደረጋል (ደንብ 13)
    until_date = datetime.now() + timedelta(minutes=13)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.answer(
            f"🚫 **የቅጣት እርምጃ!**\n\n"
            f"ተጠቃሚ {user_name} የአድሚን ትዕዛዝ ለመንካት በመሞከሩ ለ **13 ደቂቃ** ታግዷል።\n"
            f"ትዕዛዙን መጠቀም የሚችሉት አድሚኖች ብቻ ናቸው።"
        )
    except Exception as e:
        logging.error(f"Punish error: {e}")

# --- Commands ---

@dp.message(Command("srm"))
async def cmd_srm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await punish_user(message)
    
    chat_id = message.chat.id
    if active_loops.get(chat_id): return
    active_loops[chat_id] = True
    await message.answer("🎯 የኩዊዝ ውድድር ተጀመረ! መልካም ዕድል!")
    asyncio.create_task(quiz_timer(chat_id))

@dp.message(Command("stm"))
async def cmd_stm(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await punish_user(message)
    
    active_loops[message.chat.id] = False
    await message.answer("🛑 ውድድሩ በአድሚን ትዕዛዝ ቆሟል።")

@dp.message(Command("ru"))
async def cmd_ru(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await punish_user(message)
    
    cursor.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10")
    rows = cursor.fetchall()
    text = "🏆 የደረጃ ሰንጠረዥ\n\n"
    for i, row in enumerate(rows, 1): text += f"{i}. {row[0]} — {row[1]} ነጥብ\n"
    await message.answer(text)

@dp.message(Command("crt"))
async def cmd_crt(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await punish_user(message)
    
    cursor.execute("DELETE FROM scores")
    conn.commit()
    await message.answer("🧹 የደረጃ ሰንጠረዥ ተሰርዟል!")

# --- Unmute Command (በአድሚኑ Replay ተደርጎ የሚሰራ) ---
@dp.message(Command("unmute"))
async def cmd_unmute(message: types.Message):
    # አድሚን መሆኑን ማረጋገጥ
    if message.from_user.id not in ADMIN_IDS: return
    
    # ሪፕላይ መደረጉን ማረጋገጥ
    if not message.reply_to_message:
        return await message.answer("⚠️ እባክዎ እገዳው እንዲነሳ የሚፈልጉት ሰው መልዕክት ላይ **Reply** አድርገው `/unmute` ይበሉ።")
    
    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id
    
    try:
        # ሁሉንም ፐርሚሽኖች መልሶ መፍቀድ
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await message.answer(f"✅ የ {target_user.full_name} እገዳ በአድሚን ትዕዛዝ ተነስቷል። አሁን መሳተፍ ይችላል።")
    except Exception as e:
        await message.answer("❌ እገዳውን ማንሳት አልተቻለም። ቦቱ የግሩፑ አድሚን መሆኑን ያረጋግጡ።")

# (የቀረው የኩዊዝ ሎጅክ እና Main ፋንክሽን ባለፈው በሰጠሁህ መሠረት ይቀጥላል...)
