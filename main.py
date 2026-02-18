import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ---------------- LOAD ENV ----------------
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# ---------------- DATABASE ----------------

def connect():
    return sqlite3.connect("bot.db")

def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        status TEXT DEFAULT 'pending',
        score REAL DEFAULT 0,
        registered_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT,
        user_id INTEGER,
        time TEXT
    )
    """)

    conn.commit()
    conn.close()

def add_user(user_id, username, first_name):
    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if cur.fetchone():
        conn.close()
        return False

    cur.execute("""
        INSERT INTO users(user_id, username, first_name, registered_at)
        VALUES(?,?,?,?)
    """, (user_id, username, first_name, datetime.now().isoformat()))

    conn.commit()
    conn.close()
    return True

def get_user(user_id):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user

def approve_user(user_id):
    conn = connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET status='approved' WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def reject_user(user_id):
    conn = connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    conn.close()
    return users

def add_log(action, user_id):
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO logs(action,user_id,time)
        VALUES(?,?,?)
    """, (action, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ---------------- COMMANDS ----------------

async def start2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if get_user(user.id):
        await update.message.reply_text("⚠ You already requested registration.")
        return

    add_user(user.id, user.username, user.first_name)

    await update.message.reply_text("✅ Registration request sent to admin.")

    await context.bot.send_message(
        ADMIN_ID,
        f"📥 New Registration Request\n\n"
        f"Name: {user.first_name}\n"
        f"Username: @{user.username}\n"
        f"ID: {user.id}\n\n"
        f"Reply with /approve or /anapprove"
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        return

    text = update.message.reply_to_message.text

    if "ID:" not in text:
        return

    user_id = int(text.split("ID:")[1].strip())

    approve_user(user_id)
    add_log("approved", user_id)

    await context.bot.send_message(user_id, "🎉 Your registration is approved!")
    await update.message.reply_text("✔ User approved.")

async def anapprove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        return

    text = update.message.reply_to_message.text

    if "ID:" not in text:
        return

    user_id = int(text.split("ID:")[1].strip())

    reject_user(user_id)
    add_log("rejected", user_id)

    await context.bot.send_message(user_id, "❌ Your registration was rejected.")
    await update.message.reply_text("❎ User rejected.")

async def gof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)

    if not user:
        await update.message.reply_text("⚠ You are not registered.")
        return

    if user[3] != "approved":
        await update.message.reply_text("⌛ Waiting for admin approval.")
        return

    await update.message.reply_text("🚀 Welcome to the system!")

async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    users = get_all_users()

    if not users:
        await update.message.reply_text("No users.")
        return

    text = "📌 Registered Users\n\n"
    for u in users:
        text += f"{u[2]} (@{u[1]}) - {u[3]}\n"

    await update.message.reply_text(text)

# ---------------- MAIN ----------------

if __name__ == "__main__":
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start2", start2))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("anapprove", anapprove))
    app.add_handler(CommandHandler("gof", gof))
    app.add_handler(CommandHandler("pin", pin))

    print("Bot running...")
    app.run_polling()
