import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from datetime import datetime, timedelta

# --- ማዋቀሪያ ---
TOKEN = "8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE"
ADMIN_IDS = [7231324244, 8394878208]

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# --- ዳታቤዝ ማዘጋጃ ---
async def init_db():
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER, chat_id INTEGER, score REAL, muted_until TEXT, PRIMARY KEY (user_id, chat_id))''')
        await db.commit()

# --- ዋና ተግባራት ---
quiz_active = {} # የጥያቄ ሁኔታን ለመቆጣጠር

async def update_score(user_id, chat_id, points):
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, chat_id, score) VALUES (?, ?, 0)", (user_id, chat_id))
        await db.execute("UPDATE users SET score = score + ? WHERE user_id = ? AND chat_id = ?", (points, user_id, chat_id))
        await db.commit()

# --- ትእዛዞች ---

@dp.message_handler(commands=['start'])
async def start_quiz(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    chat_id = message.chat.id
    quiz_active[chat_id] = True
    await message.answer("<b>🌟 የውድድሩ ጅማሮ! በየ 4 ደቂቃው ጥያቄ ይቀርባል። መልካም እድል! 🌟</b>", parse_mode="HTML")
    
    while quiz_active.get(chat_id):
        # እዚህ ጋር ጥያቄዎችን ከፈለግክበት Subject መዝዘህ ማምጣት ትችላለህ
        poll = await bot.send_poll(
            chat_id, "ጥያቄ፡ የኢትዮጵያ ዋና ከተማ ማን ናት?", 
            options=["አዲስ አበባ", "ጎንደር", "ባህር ዳር"], 
            is_anonymous=False, type='quiz', correct_option_id=0
        )
        await asyncio.sleep(240) # 4 ደቂቃ መጠበቂያ

@dp.poll_answer_handler()
async def handle_poll_answer(quiz_answer: types.PollAnswer):
    chat_id = quiz_answer.user_id # ማስታወሻ፡ poll_answer ላይ chat_id ለማግኘት አስቸጋሪ ሊሆን ይችላል
    # ትክክለኛውን መልስ ቅደም ተከተል ለማወቅ logic እዚህ ይጨመራል
    # ለምሳሌ፡ መጀመሪያ ለመለሰ 8፣ ለዘገየ 4፣ ለተሳተፈ 1.5 ነጥብ
    await update_score(quiz_answer.user_id, 0, 1.5) # ናሙና

@dp.message_handler(commands=['stop'])
async def stop_quiz(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    quiz_active[message.chat.id] = False
    
    async with aiosqlite.connect("quiz_bot.db") as db:
        cursor = await db.execute("SELECT user_id, score FROM users WHERE chat_id = ? ORDER BY score DESC LIMIT 10", (message.chat.id,))
        winners = await cursor.fetchall()
        
        text = "<b>🏁 ውድድሩ ተጠናቋል። የደረጃ ሰንጠረዥ፡</b>\n\n"
        for i, (uid, score) in enumerate(winners, 1):
            medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
            text += f"{medal} ተወዳዳሪ {uid} - {score} ነጥብ\n"
            if i == 1: text += "🏆 የወርቅ ዋንጫ + 🎆\n"
            if i == 2: text += "🥈 የብር ዋንጫ\n"
            if i == 3: text += "🥉 የነሀስ ሽልማት\n"
            
        await message.answer(text + "\n<b>✨ እናመሰግናለን! ✨</b>", parse_mode="HTML")

@dp.message_handler(commands=['hoo'])
async def show_muted(message: types.Message):
    # የታገዱ ሰዎችን ዝርዝር ከዲቢ አምጥቶ ያሳያል
    await message.answer("የታገዱ ሰዎች ዝርዝር... (Logic)")

@dp.message_handler(commands=['clear_rank2'])
async def clear_rank(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute("DELETE FROM users WHERE chat_id = ?", (message.chat.id,))
        await db.commit()
    await message.answer("🔄 የደረጃ ሰንጠረዥ በቅቷል (Reset ተደርጓል)።")

# --- የአስተዳዳሪ ጥበቃ (Mute/Unmute) ---
@dp.message_handler(lambda m: m.reply_to_message)
async def admin_actions(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        # የአስተዳዳሪን ትዕዛዝ የነካ (Reply ያደረገ) ሰው ለ 17 ደቂቃ ይታገዳል
        if message.reply_to_message.from_user.id in ADMIN_IDS:
            until = datetime.now() + timedelta(minutes=17)
            await bot.restrict_chat_member(message.chat.id, message.from_user.id, until_date=until)
            await message.reply("⚠️ የአስተዳዳሪ ትዕዛዝ ስለነካህ ለ 17 ደቂቃ ታግደሃል!")

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
