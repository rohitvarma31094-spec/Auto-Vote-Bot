import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    MONGO_URI = os.getenv("MONGO_URI")
    OWNER_ID = int(os.getenv("OWNER_ID"))
    SESSION_FOLDER = "sessions"  # local .session backup

    # Premium emoji mapping (used in text formatting)
    PREMIUM_EMOJIS = {
        "sparkle": "✨",
        "green_tick": "✅",
        "red_cross": "❌",
        "warning": "⚠️",
        "star": "⭐",
        "fire": "🔥",
        "crown": "👑",
        "gear": "⚙️",
        "chart": "📊",
        "user": "👤",
        "group": "👥",
        "link": "🔗",
        "clock": "⏰",
        "lock": "🔒",
        "unlock": "🔓",
        "error": "🚫",
        "info": "ℹ️",
        "button_join": "🟢",
        "button_leave": "🔴",
        "button_vote": "🟣",
        "button_react": "🔵",
        "button_settings": "🟡",
    }