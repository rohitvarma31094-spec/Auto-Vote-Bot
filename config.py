import os

API_ID = int(os.environ.get("API_ID", 12345678))
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "123456:ABC-your-bot-token")

OWNER_ID = int(os.environ.get("OWNER_ID", 123456789))

DATA_DIR = "data"
SESSIONS_DIR = f"{DATA_DIR}/sessions"
ACCOUNTS_FILE = f"{DATA_DIR}/accounts.json"
ADMINS_FILE = f"{DATA_DIR}/admins.json"
SETTINGS_FILE = f"{DATA_DIR}/settings.json"
CAMPAIGNS_FILE = f"{DATA_DIR}/campaigns.json"
SCHEDULED_FILE = f"{DATA_DIR}/scheduled.json"  # ← YEH LINE ADD KARO


os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)
