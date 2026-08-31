import os

API_ID = int(os.environ.get("API_ID", 12345678))
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "123456:ABC-your-bot-token")

# Multiple owners support
OWNER_IDS = [int(x) for x in os.environ.get("OWNER_ID", "123456789").split(",") if x.strip().isdigit()]
OWNER_ID = OWNER_IDS[0] if OWNER_IDS else 123456789

# Default limit for admins if not specified (0 = Unlimited)
ADMIN_ACCOUNT_LIMIT = 0

DATA_DIR = "data"
SESSIONS_DIR = f"{DATA_DIR}/sessions"
ACCOUNTS_FILE = f"{DATA_DIR}/accounts.json"
ADMINS_FILE = f"{DATA_DIR}/admins.json"
SETTINGS_FILE = f"{DATA_DIR}/settings.json"
CAMPAIGNS_FILE = f"{DATA_DIR}/campaigns.json"
SCHEDULED_FILE = f"{DATA_DIR}/scheduled.json"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)
