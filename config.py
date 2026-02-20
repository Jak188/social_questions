import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))

ADMIN_IDS = [7231324244]
QUESTION_INTERVAL = 180
