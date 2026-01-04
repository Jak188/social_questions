import os
import asyncio
import random
import time
import json
import logging
from telegram import Update, Poll
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, PollAnswerHandler

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [8394878208, 7231324244]
QUIZ_INTERVAL = 4 * 60  # 4 ደቂቃ

# Database (In-memory)
user_scores = {}
banned_users = {} # {user_id: resume_time}
active_quizzes = {} # {poll_id: {correct_idx, start_time}}

# ጥያቄዎችን ከ JSON ፋይል ማንበቢያ
def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return []

all_questions = load_questions()

# --- HELPERS ---
def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_rank_text():
    if not user_scores: return "ገና ምንም ነጥብ አልተመዘገበም!"
    sorted_users = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 የደረጃ ሰንጠረዥ 🏆\n\n"
    icons = ["🥇", "🥈", "🥉"]
    for i, (uid, score) in enumerate(sorted_users[:10]):
        rank_icon = icons[i] if i < 3 else f"{i+1}ኛ"
        text += f"{rank_icon} ተጠቃሚ {uid}: {score} ነጥብ\n"
    return text

# --- CORE FUNCTIONS ---
async def start2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        user_scores[uid] = user_scores.get(uid, 0) - 3
        banned_users[uid] = time.time() + (17 * 60)
        await update.message.reply_text("❌ ያልተፈቀደ ሙከራ! -3 ነጥብ ተቀንሷል፣ ለ17 ደቂቃ ታግደዋል።")
        return

    context.chat_data['running'] = True
    context.chat_data['current_style'] = "General"
    await update.message.reply_text("🚀 ቦቱ ስራ ጀምሯል። ጥያቄ በየ 4 ደቂቃው ይላካል።")
    
    while context.chat_data.get('running'):
        await send_quiz_logic(context, update.effective_chat.id)
        await asyncio.sleep(QUIZ_INTERVAL)

async def send_quiz_logic(context, chat_id):
    style = context.chat_data.get('current_style', 'General')
    # በዘርፍ መለየት
    filtered = [q for q in all_questions if q['subject'] == style]
    if not filtered: filtered = all_questions # ከጠፋ ሁሉንም ይላክ
    
    q = random.choice(filtered)
    msg = await context.bot.send_poll(
        chat_id=chat_id,
        question=q['q'],
        options=q['o'],
        type=Poll.QUIZ,
        correct_option_id=q['c'],
        explanation=q['exp'],
        is_anonymous=False
    )
    active_quizzes[msg.poll.id] = {"c": q['c'], "t": time.time(), "answered": []}

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    uid = ans.user.id
    pid = ans.poll_id

    if uid in banned_users and time.time() < banned_users[uid]: return
    if pid not in active_quizzes: return
    
    quiz = active_quizzes[pid]
    if uid in quiz['answered']: return
    quiz['answered'].append(uid)

    duration = time.time() - quiz['t']
    if ans.option_ids[0] == quiz['c']:
        points = 8 if duration < 12 else 4
        user_scores[uid] = user_scores.get(uid, 0) + points
        await context.bot.send_message(uid, f"✅ ትክክል! +{points} ነጥብ 🎆")
    else:
        user_scores[uid] = user_scores.get(uid, 0) + 1.5
        await context.bot.send_message(uid, "❌ ተሳስተሃል፣ ግን ለተሳትፎ +1.5 ነጥብ ተሰጥቶሃል።")

async def stop2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        context.chat_data['running'] = False
        await update.message.reply_text(f"🛑 ቆሟል!\n\n{get_rank_text()}\n1ኛ 🏆 2ኛ 🥈 3ኛ 🥉 🎆")
    else:
        uid = update.effective_user.id
        user_scores[uid] = user_scores.get(uid, 0) - 3
        banned_users[uid] = time.time() + (17 * 60)

async def set_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    style_name = update.message.text.split('_')[0].replace('/', '').capitalize()
    context.chat_data['current_style'] = style_name
    await update.message.reply_text(f"🎯 የጥያቄ ዘርፍ ወደ '{style_name}' ተቀይሯል።")

# --- MAIN ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start2", start2))
    app.add_handler(CommandHandler("stop2", stop2))
    app.add_handler(CommandHandler("rank2", rank2 := lambda u, c: u.message.reply_text(get_rank_text())))
    
    # ለ Styles (History_sty, Mathematics_sty...)
    styles = ["History", "Mathematics", "Geography", "English"]
    for s in styles:
        app.add_handler(CommandHandler(f"{s.lower()}_sty", set_style))

    app.add_handler(PollAnswerHandler(handle_answer))
    app.run_polling()
