import logging
import random
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ቦት መረጃ ---
TOKEN = "8256328585:AAEZXXZrN608V2l4Hh_iK4ATPbACZFe-gC8"
ADMIN_IDS = [8394878208, 7231324244]

# --- ጥያቄዎች (Geography, Math, History, English) ---
QUESTIONS = [
    {"subject": "Geography", "q": "የኢትዮጵያ ትልቁ ተራራ ማን ይባላል?", "a": "ራስ ዳሽን"},
    {"subject": "Mathematics", "q": "2 + 2 * 5 ስንት ነው?", "a": "12"},
    {"subject": "History", "q": "አድዋ ጦርነት የተካሄደው በስንት ዓመተ ምህረት ነው?", "a": "1888"},
    {"subject": "English", "q": "What is the past tense of 'Go'?", "a": "went"},
    # ተጨማሪ ጥያቄዎችን እዚህ መጨመር ይቻላል...
]

# --- ዳታ ማከማቻ ---
user_scores = {}
active_game = False
asked_questions = []

# የአስተዳዳሪ መሆኑን ማረጋገጫ
def is_admin(user_id):
    return user_id in ADMIN_IDS

# /start ትዕዛዝ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    global active_game, asked_questions
    active_game = True
    asked_questions = []
    await update.message.reply_text("🎮 ውድድሩ ተጀምሯል! በየ 4 ደቂቃው ጥያቄ ይቀርባል።")
    
    while active_game:
        # ጥያቄ መምረጥ (ያልተደገመ)
        remaining = [q for q in QUESTIONS if q not in asked_questions]
        if not remaining: 
            asked_questions = [] # ካለቁ እንደገና እንዲጀምር
            remaining = QUESTIONS
            
        current_q = random.choice(remaining)
        asked_questions.append(current_q)
        
        context.bot_data['current_answer'] = current_q['a']
        context.bot_data['answered_users'] = []
        
        await update.message.reply_text(f"📚 ትምህርት: {current_q['subject']}\n❓ ጥያቄ: {current_q['q']}")
        
        # ለ 4 ደቂቃ መጠበቅ
        await asyncio.sleep(240) 

# መልስ መቀበያ እና ነጥብ አሰጣጥ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_scores
    if not active_game or 'current_answer' not in context.bot_data: return
    
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    answer = update.message.text.strip()
    correct_answer = context.bot_data['current_answer']
    
    if user_id in context.bot_data['answered_users']: return # አንድ ሰው አንዴ ብቻ

    if answer.lower() == correct_answer.lower():
        # ነጥብ አሰጣጥ
        if not context.bot_data['answered_users']: # ቀድሞ ለመለሰ
            points = 8
        else: # ዘግይቶ ለመለሰ
            points = 4
        context.bot_data['answered_users'].append(user_id)
    else:
        points = 1.5 # ለተሳተፈ
        context.bot_data['answered_users'].append(user_id)

    user_scores[user_name] = user_scores.get(user_name, 0) + points
    await update.message.reply_text(f"✅ {user_name} {points} ነጥብ አግኝተሃል/ሻል!")

# /rank ትዕዛዝ
async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_scores:
        await update.message.reply_text("ገና ምንም ነጥብ አልተመዘገበም።")
        return
    sorted_rank = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)
    msg = "🏆 የደረጃ ሰንጠረዥ:\n"
    for i, (name, score) in enumerate(sorted_rank, 1):
        msg += f"{i}. {name}: {score} ነጥብ\n"
    await update.message.reply_text(msg)

# /stop ትዕዛዝ
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    global active_game
    active_game = False
    await update.message.reply_text("🛑 ውድድሩ ቆሟል።")

# /clear_rank ትዕዛዝ
async def clear_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    global user_scores
    user_scores = {}
    await update.message.reply_text("🧹 የደረጃ ሰንጠረዥ ጸድቷል።")

# ዋና ማሰሪያ
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("clear_rank", clear_rank))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("ቦቱ ስራ ጀምሯል...")
    app.run_polling()
