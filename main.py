import asyncio
import json
import random
import os
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from datetime import datetime, timedelta

# --- CONFIGURATION ---
API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [123456789]  # የራስህን ID እዚህ ተካ
QUESTIONS_FILE = "questions.json"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# የውሂብ ማከማቻ
group_data = {}  # {group_id: {"scores": {}, "active": False, "muted": {}}}
questions_list = []

# ፋይሉን ማንበብ
try:
    with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
        questions_list = json.load(f)
except Exception as e:
    print(f"Error loading JSON: {e}")

def get_rank_text(scores):
    if not scores: return "ምንም ተሳታፊ የለም።"
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 **የደረጃ ሰንጠረዥ** 🏆\n\n"
    for i, (user_id, score) in enumerate(sorted_scores[:10], 1):
        text += f"{i}. User {user_id}: {score} ነጥብ\n"
    return text

@dp.message_handler(commands=['start2'])
async def start_quiz(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    gid = message.chat.id
    if gid not in group_data: group_data[gid] = {"scores": {}, "active": True, "muted": {}}
    group_data[gid]["active"] = True
    await message.answer("🚀 **ውድድሩ በደመቀ ሁኔታ ተጀምሯል!** በየ 4 ደቂቃው ጥያቄ ይቀርባል።")
    
    while group_data[gid]["active"]:
        q = random.choice(questions_list)
        poll = await bot.send_poll(
            gid, q['q'], q['o'], type='quiz', correct_option_id=q['c'], is_anonymous=False
        )
        
        # ለ 4 ደቂቃ መጠበቅ
        await asyncio.sleep(240) 
        
        # ማብራሪያ መላክ
        if 'exp' in q:
            await bot.send_message(gid, f"💡 **ማብራሪያ፦**\n{q['exp']}")
        
        await bot.stop_poll(gid, poll.message_id)

@dp.poll_answer_handler()
async def handle_poll_answer(quiz_answer: types.PollAnswer):
    gid = quiz_answer.user_id # ለቀላልነት
    # እዚህ ጋር ነጥብ የመቁጠር logic ይገባል (እንደየ ፍጥነቱ)

@dp.message_handler(commands=['stop2'])
async def stop_quiz(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    gid = message.chat.id
    group_data[gid]["active"] = False
    
    scores = group_data[gid]["scores"]
    rank_text = get_rank_text(scores)
    
    final_msg = f"🏁 **ውድድሩ ተጠናቋል!**\n\n{rank_text}\n"
    final_msg += "\n🥇 3 የወርቅ ዋንጫ\n🥈 2 የብር ዋንጫ\n🥉 1 የነሀስ ሽልማት እና 🎆"
    
    await message.answer(final_msg)
    await bot.send_dice(gid, emoji="🎰") # ለሊቨርፑል/ሪችት ማሳያ

@dp.message_handler(commands=['clear_rank2'])
async def clear_rank(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    group_data[message.chat.id]["scores"] = {}
    await message.answer("🧹 የነጥብ ሰሌዳው ወደ መጀመሪያ ተመልሷል።")

@dp.message_handler(commands=['hoo'])
async def show_muted(message: types.Message):
    gid = message.chat.id
    muted_users = group_data.get(gid, {}).get("muted", {})
    if not muted_users:
        await message.answer("የታገደ ሰው የለም።")
    else:
        text = "🚫 **የታገዱ ተሳታፊዎች፦**\n"
        for uid, time in muted_users.items():
            text += f"- User {uid} (እስከ {time})\n"
        await message.answer(text)

# --- የማገጃ ስርአት (Admin Commands Protection) ---
@dp.message_handler(lambda m: any(m.text.startswith(c) for c in ['/', 'History_srm']))
async def protect_admin_commands(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        gid = message.chat.id
        until = datetime.now() + timedelta(minutes=17)
        group_data[gid]["muted"][message.from_user.id] = until
        await bot.restrict_chat_member(gid, message.from_user.id, until_date=until)
        await message.reply("⚠️ **ማስጠንቀቂያ!** የአድሚን ትዕዛዝ ስለነካህ ለ 17 ደቂቃ ታግደሃል።")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
