import sqlite3

db = sqlite3.connect("quiz.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    score REAL DEFAULT 0,
    approved INTEGER DEFAULT 0
)
""")

def add_user(user_id, username):
    cursor.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?,?)",
                   (user_id, username))
    db.commit()

def approve_user(user_id):
    cursor.execute("UPDATE users SET approved=1 WHERE user_id=?", (user_id,))
    db.commit()

def is_approved(user_id):
    cursor.execute("SELECT approved FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row and row[0] == 1

def add_score(user_id, points):
    cursor.execute("UPDATE users SET score=score+? WHERE user_id=?",
                   (points, user_id))
    db.commit()

def get_top():
    cursor.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 15")
    return cursor.fetchall()
