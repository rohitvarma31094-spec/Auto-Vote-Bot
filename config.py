import os

# ── Persistent data dir (Railway Volume) ──
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)

API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "your_api_hash")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token")
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8076739291,8880226666").split(",") if x.strip()]

SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
ADMINS_FILE = os.path.join(DATA_DIR, "admins.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
CAMPAIGNS_FILE = os.path.join(DATA_DIR, "campaigns.json")
SCHEDULED_FILE = os.path.join(DATA_DIR, "scheduled.json")
