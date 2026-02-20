from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)
from config import TOKEN, ADMIN_IDS
from database import add_user
from quiz_engine import check_answer
from ranking import rank_command
from moderation import approve
from scheduler import quiz_loop, stop_quiz

import asyncio

async def register(update, context):
    user = update.effective_user
    add_user(user.id, user.username)
    await update.message.reply_text("✅ Registered")

async def start2(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("🔥 Quiz Started")
    asyncio.create_task(quiz_loop(context))

async def stop2(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    stop_quiz()
    await update.message.reply_text("🛑 Stopped")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("start2", start2))
    app.add_handler(CommandHandler("stop2", stop2))
    app.add_handler(CommandHandler("rank2", rank_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_answer))

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
