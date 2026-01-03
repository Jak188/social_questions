import logging
import asyncio
import sqlite3
import json
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# --- CONFIGURATION ---
# የሰጠኸው ቶከን እና አድሚን አይዲ እዚህ ገብቷል
API_TOKEN = '8256328585:AAFRcSR0pxfHIyVrJQGpUIrbOOQ7gIcY0cE'
ADMIN_IDS = [7231324244, 8394878208] 
QUIZ_INTERVAL = 240 # ህግ 1: 4 ደቂቃ

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, parse_mode="Markdown")
dp = Dispatcher(bot)

# --- DATABASE SETUP (ህግ 17) ---
def init_db():
    conn = sqlite3.connect("quiz_pro.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, name TEXT, score REAL DEFAULT 0, 
                  muted_until TEXT, is_muted INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS active_polls 
                 (poll_id TEXT PRIMARY KEY, chat_id INTEGER, correct_id INTEGER, 
                  answered_count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

# --- HELPERS ---
def update_score(user_id, name, points):
    conn = sqlite3.connect("quiz_pro.db")
    conn.execute("INSERT OR IGNORE INTO users (id, name, score) VALUES (?, ?, 0)", (user_id, name))
    conn.execute("UPDATE users SET score = score + ?, name = ? WHERE id = ?", (points, name, user_id))
    conn.commit()
    conn.close()

def is_user_muted(user_id):
    conn = sqlite3.connect("quiz_pro.db")
    res = conn.execute("SELECT muted_until FROM users WHERE id = ? AND is_muted = 1", (user_id,)).fetchone()
    conn.close()
    if res:
        until = datetime.fromisoformat(res[0])
        if datetime.now() < until: return True
    return False

# --- MUTE PROTECTION (ህግ 7) ---
@dp.message_handler(lambda m: is_user_muted(m.from_user.id))
async def check_mute(message: types.Message):
    await message.delete()

# --- ADMIN COMMANDS ---

# ህግ 7 & 8: ማገድ (Mute)
@dp.message_handler(commands=['mute2'])
async def mute_user(message: types.Message):
    if message.from_id not in ADMIN_IDS or not message.reply_to_message: return
    target = message.reply_to_message.from_user
    until = (datetime.now() + timedelta(minutes=17)).isoformat()
    
    conn = sqlite3.connect("quiz_pro.db")
    conn.execute("UPDATE users SET muted_until = ?, is_muted = 1 WHERE id = ?", (until, target.id))
    conn.commit()
    conn.close()
    await message.answer(f"🚫 {target.full_name} የአድሚን ትእዛዝ በመንካትህ ለ 17 ደቂቃ ታግደሃል!")

# ህግ 8: እገዳ ማንሳት
@dp.message_handler(commands=['un_mute2'])
async def unmute_user(message: types.Message):
    if message.from_id not in ADMIN_IDS or not message.reply_to_message: return
    target = message.reply_to_message.from_user
    conn = sqlite3.connect("quiz_pro.db")
    conn.execute("UPDATE users SET is_muted = 0 WHERE id = ?", (target.id,))
    conn.commit()
    conn.close()
    await message.reply(f"✅ {target.full_name} እገዳው ተነስቷል። ዳግመኛ እንዳትሳሳት! ⚠️")

# ህግ 9: የታገዱ ዝርዝር
@dp.message_handler(commands=['hoo'])
async def list_muted(message: types.Message):
    conn = sqlite3.connect("quiz_pro.db")
    muted = conn.execute("SELECT name FROM users WHERE is_muted = 1").fetchall()
    conn.close()
    txt = "🚫 **የታገዱ ተወዳዳሪዎች:**\n" + "\n".join([m[0] for m in muted]) if muted else "ማንም የታገደ የለም።"
    await message.answer(txt)

# --- QUIZ ENGINE (ህግ 1, 11, 13, 14, 16) ---
active_quizzes = {}

async def run_quiz_loop(chat_id, subject):
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            all_q = json.load(f)
        questions = [q for q in all_q if q.get('subject', '').lower() == subject.lower()]
        
        if not questions:
            await bot.send_message(chat_id, "❌ ለዚህ ሰብጀክት ጥያቄ አልተገኘም!")
            return

        await bot.send_message(chat_id, f"🌟✨ **የ {subject} ውድድር በደመቀ ሁኔታ ተጀመረ!** ✨🌟\n(በየ 4 ደቂቃው ይጠየቃል)")

        while chat_id in active_quizzes:
            q = random.choice(questions)
            poll = await bot.send_poll(
                chat_id, q['q'], q['o'], type='quiz', 
                correct_option_id=q['c'], is_anonymous=False,
                explanation=q.get('exp', "ትክክለኛ መልስ!"),
                open_period=230 
            )
            
            conn = sqlite3.connect("quiz_pro.db")
            conn.execute("INSERT INTO active_polls VALUES (?, ?, ?, 0)", (poll.poll.id, chat_id, q['c']))
            conn.commit()
            conn.close()
            
            await asyncio.sleep(QUIZ_INTERVAL)
    except Exception as e:
        logging.error(f"Error in quiz: {e}")

@dp.message_handler(commands=['start2'])
async def cmd_start(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    subj = message.get_args() or "General"
    if message.chat.id in active_quizzes: return
    active_quizzes[message.chat.id] = asyncio.create_task(run_quiz_loop(message.chat.id, subj))

# ህግ 5, 12, 13: ማቆም እና ሽልማት
@dp.message_handler(commands=['stop2'])
async def cmd_stop(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    if message.chat.id in active_quizzes:
        active_quizzes[message.chat.id].cancel()
        del active_quizzes[message.chat.id]
        
        conn = sqlite3.connect("quiz_pro.db")
        top = conn.execute("SELECT name, score FROM users ORDER BY score DESC LIMIT 10").fetchall()
        conn.close()
        
        res = "🏆 **የውድድሩ ማጠቃለያ ውጤት** 🏆\n\n"
        # ህግ 5: የወርቅ፣ የብር እና የነሃስ ዋንጫ
        for i, (name, score) in enumerate(top):
            if i == 0: rank_icon = "🥇 🥇 🥇 (የወርቅ ዋንጫ)"
            elif i == 1: rank_icon = "🥈 🥈 (የብር ዋንጫ)"
            elif i == 2: rank_icon = "🥉 (የነሐስ ዋንጫ)"
            else: rank_icon = "🏅"
            
            res += f"{rank_icon} {i+1}ኛ. {name} - {score} ነጥብ\n"
        
        await message.answer(f"✨✨ **ውድድሩ በደመቀ ሁኔታ ተጠናቋል!** ✨🌟\n\n{res}\n🎇 እንኳን ደስ አላችሁ! 🎇")

# ህግ 10: ነጥብ ማጽጃ
@dp.message_handler(commands=['clear_rank2'])
async def cmd_clear(message: types.Message):
    if message.from_id not in ADMIN_IDS: return
    conn = sqlite3.connect("quiz_pro.db")
    conn.execute("UPDATE users SET score = 0")
    conn.commit()
    conn.close()
    await message.answer("♻️ ሁሉም ነጥቦች ወደ ዜሮ ተመልሰዋል!")

# --- SCORING LOGIC (ህግ 2, 3, 4, 6, 15) ---
@dp.poll_answer_handler()
async def handle_poll_answer(ans: types.PollAnswer):
    if is_user_muted(ans.user.id): return

    conn = sqlite3.connect("quiz_pro.db")
    poll_info = conn.execute("SELECT correct_id, answered_count FROM active_polls WHERE poll_id = ?", (ans.poll_id,)).fetchone()
    
    if poll_info:
        correct_id, count = poll_info
        if ans.option_ids[0] == correct_id:
            # ነጥብ አሰጣጥ ህግ 2 እና 3
            if count == 0:
                points = 8 
                await bot.send_message(ans.user.id, f"🥇 ፈጣን ነህ! +8 ነጥብ አገኘህ 🎇\n{ans.user.full_name} ቀድሞ መለሰ! ✅")
            else:
                points = 4 
                await bot.send_message(ans.user.id, "🎯 ትክክል! +4 ነጥብ 🎇")
            
            conn.execute("UPDATE active_polls SET answered_count = answered_count + 1 WHERE poll_id = ?", (ans.poll_id,))
        else:
            # ህግ 4: ለተሳተፈ 1.5 ነጥብ
            points = 1.5 
            await bot.send_message(ans.user.id, "Attempted! +1.5 ነጥብ (ለተሳትፎ)")
        
        conn.commit()
        conn.close()
        update_score(ans.user.id, ans.user.full_name, points)

if __name__ == '__main__':
    print("Bot is running...")
    executor.start_polling(dp, skip_updates=True)
