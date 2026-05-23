import os
from dotenv import load_dotenv

load_dotenv()

# ⚠️ यहाँ अपना नया token डालें (public मत करें)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_NEW_TOKEN_HERE")

# अपना Telegram User ID (https://t.me/userinfobot से लें)
ADMIN_IDS = [8931476875]  # ← Your ID

DATABASE_URL = "sqlite+aiosqlite:///store.db"
