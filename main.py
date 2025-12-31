import os
import logging
import random
from flask import Flask
from threading import Thread
from telegram import Update, Poll
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Flask Server (Railway 24/7 እንዲሰራ) ---
server = Flask('')

@server.route('/')
def home():
    return "Quiz Bot is Active and Running!"

def run():
    port = int(os.environ.get('PORT', 8080))
    server.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- ጥያቄዎቹ (እዚህ ጋር 800ዎቹም ጥያቄዎች ይካተታሉ) ---
# ለማሳያ ያህል ጥቂቶቹን አስገብቻለሁ፣ ቀሪዎቹን በተመሳሳይ ፎርማት መጨመር ትችላለህ
questions_db = [
    {"subject": "Mathematics", "q": "Find the slope of y = 5x - 3.", "o": ["-3", "5", "0", "1"], "c": 1, "exp": "In y = mx + b, m is the slope. Here m=5."},
    {"subject": "Geography", "q": "What is the main cause of tides?", "o": ["Rotation", "Moon's Gravity", "Volcanoes", "Heat"], "c": 1, "exp": "Tides are caused by the Moon's gravitational pull."},
    {"subject": "History", "q": "In which year was the Battle of Adwa fought?", "o": ["1889", "1896", "1935", "1941"], "c": 1, "exp": "The Battle of Adwa took place in 1896."},
    {"subject": "English", "q": "Which is a synonym of 'Abundant'?", "o": ["Scarce", "Plentiful", "Rare", "Small"], "c": 1, "exp": "'Plentiful' means existing in great quantities."},
    # ... ቀሪዎቹን 796 ጥያቄዎች እዚህ ዝርዝር ውስጥ ይጨምሩ
]

# --- ቦት ተግባራት ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    await update.message.reply_text(f"ሰላም {user}! እንኳን ወደ Entrance/Remedial መለማመጃ ቦት መጡ።\n\nጥያቄ ለመጀመር /quiz ይበሉ።")

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q_data = random.choice(questions_db)
    
    # በስክሪንሾቱ መልክ Subject Header መጨመር
    question_text = f"📚 Subject: {q_data['subject']}\n\n{q_data['q']}"
    
    await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=question_text,
        options=q_data['o'],
        type=Poll.QUIZ,
        correct_option_id=q_data['c'],
        explanation=q_data['exp'],
        is_anonymous=False
    )

if __name__ == '__main__':
    # አንተ የሰጠኸኝ Token
    TOKEN = "8256328585:AAEZXXZrN608V2l4Hh_iK4ATPbACZFe-gC8"
    
    keep_alive() # ሰርቨሩን በጀርባ ያስነሳል
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz))
    
    print("ቦቱ ስራ ጀምሯል...")
    app.run_polling()
