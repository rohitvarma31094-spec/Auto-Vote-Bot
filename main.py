import asyncio
import json
import os
import random
import re
import threading
import time
import shutil
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

from telethon import TelegramClient, events, Button, errors
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, FloodWaitError, UserAlreadyParticipantError,
    ChannelPrivateError, ChatAdminRequiredError, InviteHashInvalidError,
    InviteHashExpiredError, InviteHashEmptyError, UserNotParticipantError,
    ChannelInvalidError, ReactionInvalidError,
    TimeoutError as TelethonTimeoutError
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    ImportChatInviteRequest, SendVoteRequest, GetBotCallbackAnswerRequest,
    CheckChatInviteRequest, GetMessagesRequest,
    SendReactionRequest
)

from telethon.tl.functions.channels import (
    JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest,
    GetParticipantRequest
)
from telethon.tl.types import (
    PeerChannel, ReactionEmoji, ReactionCustomEmoji, InputPeerChannel,
    MessageEntityTextUrl, Channel, Chat, ChannelParticipant,
    ChannelParticipantBanned, ChannelParticipantCreator,
    ChannelParticipantAdmin, Message, MessageService, ChannelFull,
    ChatReactionsAll, ChatReactionsNone, ChatReactionsSome,
    InputPeerChannel, InputPeerChat, InputPeerUser
)

try:
    from telethon.tl.types import KeyboardButtonCallback, KeyboardButtonStyle
    HAS_BTN_STYLE = True
except ImportError:
    HAS_BTN_STYLE = False

import config

os.makedirs(config.SESSIONS_DIR, exist_ok=True)
LOCK = threading.Lock()

# ==========================================================
#  AUTO-BACKUP & RESTORE SYSTEM
# ==========================================================

BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

def create_backup():
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"backup_{timestamp}")
        os.makedirs(backup_path, exist_ok=True)
        
        if os.path.exists(config.ACCOUNTS_FILE):
            shutil.copy2(config.ACCOUNTS_FILE, os.path.join(backup_path, "accounts.json"))
        if os.path.exists(config.ADMINS_FILE):
            shutil.copy2(config.ADMINS_FILE, os.path.join(backup_path, "admins.json"))
        if os.path.exists(config.SETTINGS_FILE):
            shutil.copy2(config.SETTINGS_FILE, os.path.join(backup_path, "settings.json"))
        if os.path.exists(config.CAMPAIGNS_FILE):
            shutil.copy2(config.CAMPAIGNS_FILE, os.path.join(backup_path, "campaigns.json"))
        if os.path.exists(config.SCHEDULED_FILE):
            shutil.copy2(config.SCHEDULED_FILE, os.path.join(backup_path, "scheduled.json"))
        
        print(f"[BACKUP] Created backup at {backup_path}")
        
        backups = sorted([d for d in os.listdir(BACKUP_DIR) if d.startswith("backup_")])
        if len(backups) > 5:
            for old_backup in backups[:-5]:
                shutil.rmtree(os.path.join(BACKUP_DIR, old_backup))
                print(f"[BACKUP] Removed old backup: {old_backup}")
        
        return backup_path
    except Exception as e:
        print(f"[BACKUP] Error creating backup: {e}")
        return None

def restore_from_backup(backup_path=None):
    try:
        if backup_path is None:
            backups = sorted([d for d in os.listdir(BACKUP_DIR) if d.startswith("backup_")])
            if not backups:
                print("[BACKUP] No backups found to restore")
                return False
            backup_path = os.path.join(BACKUP_DIR, backups[-1])
        
        print(f"[BACKUP] Restoring from {backup_path}")
        
        accounts_backup = os.path.join(backup_path, "accounts.json")
        if os.path.exists(accounts_backup):
            shutil.copy2(accounts_backup, config.ACCOUNTS_FILE)
            print(f"[BACKUP] Restored accounts.json")
        
        admins_backup = os.path.join(backup_path, "admins.json")
        if os.path.exists(admins_backup):
            shutil.copy2(admins_backup, config.ADMINS_FILE)
            print(f"[BACKUP] Restored admins.json")
        
        settings_backup = os.path.join(backup_path, "settings.json")
        if os.path.exists(settings_backup):
            shutil.copy2(settings_backup, config.SETTINGS_FILE)
            print(f"[BACKUP] Restored settings.json")
        
        campaigns_backup = os.path.join(backup_path, "campaigns.json")
        if os.path.exists(campaigns_backup):
            shutil.copy2(campaigns_backup, config.CAMPAIGNS_FILE)
            print(f"[BACKUP] Restored campaigns.json")
        
        scheduled_backup = os.path.join(backup_path, "scheduled.json")
        if os.path.exists(scheduled_backup):
            shutil.copy2(scheduled_backup, config.SCHEDULED_FILE)
            print(f"[BACKUP] Restored scheduled.json")
        
        print(f"[BACKUP] Restore completed successfully!")
        return True
    except Exception as e:
        print(f"[BACKUP] Error restoring backup: {e}")
        return False

def safe_save(data, file_path):
    try:
        if os.path.exists(file_path):
            backup_file = file_path + ".bak"
            shutil.copy2(file_path, backup_file)
        
        tmp = file_path + ".tmp"
        with LOCK:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, file_path)
        
        backup_file = file_path + ".bak"
        if os.path.exists(backup_file):
            os.remove(backup_file)
        
        return True
    except Exception as e:
        print(f"[SAFE_SAVE] Error saving {file_path}: {e}")
        backup_file = file_path + ".bak"
        if os.path.exists(backup_file):
            try:
                shutil.copy2(backup_file, file_path)
                print(f"[SAFE_SAVE] Restored from backup for {file_path}")
            except:
                pass
        return False

def jsave(path, data):
    safe_save(data, path)

def jload(path, default):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    
    if not os.path.exists(path):
        backup_file = path + ".bak"
        if os.path.exists(backup_file):
            try:
                shutil.copy2(backup_file, path)
                print(f"[JLOAD] Restored from backup: {path}")
            except:
                pass
        
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump(default, f)
            return default
    
    try:
        with LOCK:
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        print(f"[JLOAD] Error loading {path}: {e}")
        
        backup_file = path + ".bak"
        if os.path.exists(backup_file):
            try:
                with LOCK:
                    with open(backup_file) as f:
                        data = json.load(f)
                shutil.copy2(backup_file, path)
                print(f"[JLOAD] Restored {path} from backup")
                return data
            except:
                pass
        
        backups = sorted([d for d in os.listdir(BACKUP_DIR) if d.startswith("backup_")])
        if backups:
            latest_backup = os.path.join(BACKUP_DIR, backups[-1])
            backup_file_path = os.path.join(latest_backup, os.path.basename(path))
            if os.path.exists(backup_file_path):
                try:
                    with LOCK:
                        with open(backup_file_path) as f:
                            data = json.load(f)
                    shutil.copy2(backup_file_path, path)
                    print(f"[JLOAD] Restored {path} from backup directory")
                    return data
                except:
                    pass
        
        try:
            os.replace(path, path + ".corrupt")
        except:
            pass
        with open(path, "w") as f:
            json.dump(default, f)
        return default

# ==========================================================
#  STYLISH FONTS
# ==========================================================

_BOLD = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
)

def fancy(t: str) -> str:
    return str(t).translate(_BOLD)

async def send(e, text, **kw):
    f = getattr(e, "reply", None)
    if f is None:
        f = e.respond
    return await f(text, **kw)

def styled_btn(text, data, style=None):
    if HAS_BTN_STYLE and style:
        flag_map = {
            "primary": dict(bg_primary=True),
            "success": dict(bg_success=True),
            "danger":  dict(bg_danger=True),
        }
        try:
            return KeyboardButtonCallback(
                text,
                data if isinstance(data, bytes) else data.encode(),
                style=KeyboardButtonStyle(**flag_map[style]))
        except TypeError:
            pass
    return Button.inline(text, data)

# ==========================================================
#  PREMIUM EMOJIS
# ==========================================================

class PremiumEmojis:
    VOTE = "🗳️"; JOIN = "➕"; CANCEL = "❌"; MAIN_MENU = "🏠"
    BACK = "🔙"; CREATE = "🚀"; CONNECT = "🔗"; MANAGE = "🛠️"
    ADMIN = "👑"; STATS = "📊"; SETTINGS = "⚙️"; CLEAR = "🗑️"
    CHANNEL = "📡"; CONFIRM = "✅"; CHART = "📈"; CROWN = "👑"
    ALERT = "🚨"; SEARCH = "🔍"; SPEAKER = "🔊"; LOCK = "🔒"
    ID = "🆔"; STAR = "⭐"; REQUEST = "📩"; CLOCK = "⏰"; LIST = "📋"

    REACTION_EMOJIS = {
        "☺️": "6289363706681755465",
        "🔥": "6334449730734529256",
        "❤️": "6237558987978447573",
        "⭐": "6239815031219820750",
        "💎": "6240003971126139705",
        "👑": "6332246180583447893",
        "🎉": "6240085923397114865",
        "👍": "6237867138997034625",
        "😍": "6334437167955188087",
        "🚀": "5188481279963715781",
        "🙌": "6237621707385871360",
        "👏": "6237621707385871360",
    }

# ==========================================================
#  STORAGE (with auto-backup)
# ==========================================================

# Load data
accounts = jload(config.ACCOUNTS_FILE, [])
raw_admins = jload(config.ADMINS_FILE, [])
admins = []
for a in raw_admins:
    if isinstance(a, int):
        admins.append({"id": a, "limit": 0, "name": "Unknown"})
    else:
        admins.append(a)
settings = jload(config.SETTINGS_FILE, {})
campaigns = jload(config.CAMPAIGNS_FILE, [])
active_campaigns = {}
campaign_history = jload(config.CAMPAIGNS_FILE + "_history", [])
running_campaigns = {}

# Save functions
def save_accounts():
    jsave(config.ACCOUNTS_FILE, accounts)
    create_backup()

def save_admins():
    jsave(config.ADMINS_FILE, admins)
    create_backup()

def save_settings():
    jsave(config.SETTINGS_FILE, settings)
    create_backup()

def save_campaigns():
    jsave(config.CAMPAIGNS_FILE, campaigns)
    create_backup()

def save_campaign_history():
    jsave(config.CAMPAIGNS_FILE + "_history", campaign_history)

scheduled = []
def load_scheduled():
    global scheduled
    try:
        with open(config.SCHEDULED_FILE) as f:
            scheduled = json.load(f)
    except FileNotFoundError:
        scheduled = []
    except Exception as ex:
        print(f"[scheduled] load error: {ex}")
        scheduled = []

def save_scheduled():
    try:
        jsave(config.SCHEDULED_FILE, scheduled)
        create_backup()
    except Exception as ex:
        print(f"[scheduled] save error: {ex}")

load_scheduled()

# ==========================================================
#  ON STARTUP - AUTO RESTORE IF ACCOUNTS EMPTY
# ==========================================================

def check_and_restore_on_startup():
    """Check if accounts are empty and try to restore from backup"""
    try:
        current_accounts = jload(config.ACCOUNTS_FILE, [])
        
        if not current_accounts:
            print("[STARTUP] No accounts found! Attempting restore from backup...")
            
            backups = sorted([d for d in os.listdir(BACKUP_DIR) if d.startswith("backup_")])
            if backups:
                latest_backup = os.path.join(BACKUP_DIR, backups[-1])
                accounts_backup = os.path.join(latest_backup, "accounts.json")
                
                if os.path.exists(accounts_backup):
                    try:
                        with open(accounts_backup) as f:
                            restored_accounts = json.load(f)
                        if restored_accounts:
                            jsave(config.ACCOUNTS_FILE, restored_accounts)
                            print(f"[STARTUP] ✅ Restored {len(restored_accounts)} accounts from backup!")
                            
                            for file_name in ["admins.json", "settings.json", "campaigns.json", "scheduled.json"]:
                                backup_file = os.path.join(latest_backup, file_name)
                                if os.path.exists(backup_file):
                                    target_file = getattr(config, file_name.upper().replace(".JSON", "_FILE"), None)
                                    if target_file:
                                        shutil.copy2(backup_file, target_file)
                                        print(f"[STARTUP] Restored {file_name}")
                            
                            # Reload all data
                            global accounts, admins, settings, campaigns, scheduled
                            accounts = jload(config.ACCOUNTS_FILE, [])
                            raw_admins = jload(config.ADMINS_FILE, [])
                            admins = []
                            for a in raw_admins:
                                if isinstance(a, int):
                                    admins.append({"id": a, "limit": 0, "name": "Unknown"})
                                else:
                                    admins.append(a)
                            settings = jload(config.SETTINGS_FILE, {})
                            campaigns = jload(config.CAMPAIGNS_FILE, [])
                            load_scheduled()
                            return True
                    except Exception as e:
                        print(f"[STARTUP] Error restoring from backup: {e}")
            
            for file_path in [config.ACCOUNTS_FILE, config.ADMINS_FILE, config.SETTINGS_FILE, config.CAMPAIGNS_FILE]:
                backup_file = file_path + ".bak"
                if os.path.exists(backup_file):
                    try:
                        shutil.copy2(backup_file, file_path)
                        print(f"[STARTUP] Restored {file_path} from .bak")
                    except:
                        pass
            
            global accounts
            accounts = jload(config.ACCOUNTS_FILE, [])
            if accounts:
                print(f"[STARTUP] ✅ Loaded {len(accounts)} accounts after restore")
                return True
        
        return False
    except Exception as e:
        print(f"[STARTUP] Error in check_and_restore: {e}")
        return False

# ==========================================================
#  ACCESS CONTROL
# ==========================================================

def is_owner(uid):
    return uid in config.OWNER_IDS

def is_admin(uid):
    return is_owner(uid) or uid in [a['id'] for a in admins]

def get_user_limit(uid):
    if is_owner(uid):
        return float('inf')
    admin_data = next((a for a in admins if a['id'] == uid), None)
    if admin_data:
        if admin_data.get('limit', 0) == 0:
            return float('inf')
        return int(admin_data.get('limit', 0))
    return 0

def get_admin_accounts(uid):
    if is_owner(uid):
        return accounts.copy()
    limit = get_user_limit(uid)
    if limit == float('inf'):
        return accounts.copy()
    user_accs = [a for a in accounts if a.get('owner') == uid]
    if len(user_accs) >= limit:
        return user_accs[:int(limit)]
    remaining = int(limit) - len(user_accs)
    other_accs = [a for a in accounts if a.get('owner') != uid]
    return user_accs + other_accs[:remaining]

def my_accounts(uid, limit=None):
    if limit is None:
        limit = get_user_limit(uid)
    user_accs = [a for a in accounts if a.get('owner') == uid]
    if limit == float('inf') or limit is None:
        return user_accs
    return user_accs[:int(limit)]

def get_total_accounts():
    return len(accounts)

def get_admin_usage_stats(admin_id):
    admin_campaigns = [c for c in campaigns if c.get('owner') == admin_id]
    return {
        'total_campaigns': len(admin_campaigns),
        'total_votes': sum(c.get('ok', 0) for c in admin_campaigns),
        'last_campaign': admin_campaigns[-1]['time'] if admin_campaigns else 'Never'
    }

# ==========================================================
#  USER STATE & CLIENTS
# ==========================================================

user_state = {}
clients = {}
client_lock = threading.Lock()

def state(uid):
    return user_state.setdefault(uid, {})

def reset(uid):
    user_state.pop(uid, None)

def get_settings(uid):
    return settings.setdefault(str(uid), {"delay_min": 1.0, "delay_max": 2.5})

async def get_client(acc):
    phone = acc["phone"]
    with client_lock:
        if phone in clients and clients[phone].is_connected():
            return clients[phone]
    try:
        c = TelegramClient(
            StringSession(acc["string"]),
            config.API_ID, config.API_HASH,
            device_model="Desktop", system_version="Windows 10",
            app_version="4.16.8", connection_retries=3, retry_delay=2
        )
        await c.connect()
        if not await c.is_user_authorized():
            await c.disconnect()
            return None
        with client_lock:
            clients[phone] = c
        return c
    except Exception as e:
        print(f"[client] Error for {acc.get('phone', 'unknown')}: {e}")
        return None

async def save_session_account(c, owner):
    try:
        me = await c.get_me()
        phone = me.phone or "unknown"
        acc = {
            "phone": phone,
            "name": (me.first_name or "").strip(),
            "string": c.session.save(),
            "id": me.id,
            "owner": owner
        }
        with client_lock:
            clients[phone] = c
        for i, a in enumerate(accounts):
            if a["phone"] == phone:
                accounts[i] = acc
                save_accounts()
                return acc
        accounts.append(acc)
        save_accounts()
        return acc
    except Exception as e:
        print(f"[save_session] Error: {e}")
        raise

async def validate_session_string(s, owner):
    c = TelegramClient(
        StringSession(s.strip()),
        config.API_ID, config.API_HASH,
        device_model="Desktop", system_version="Windows 10"
    )
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        raise ValueError("Session expired / not authorized")
    return await save_session_account(c, owner)

# ==========================================================
#  ENTITY RESOLUTION
# ==========================================================

async def resolve_entity(client, ref):
    kind, val = ref
    try:
        if kind == "username":
            try:
                return await client.get_entity(val)
            except Exception:
                if not val.startswith('@'):
                    return await client.get_entity('@' + val)
                raise
        elif kind == "c":
            try:
                return await client.get_entity(PeerChannel(val))
            except Exception:
                try:
                    async for d in client.iter_dialogs():
                        if d.id == int(f"-100{val}"):
                            return d.entity
                except Exception:
                    pass
            return None
        elif kind == "id":
            cid = val
            if cid < 0:
                cid = abs(cid)
                if cid > 1000000000000:
                    cid -= 1000000000000
            try:
                return await client.get_entity(PeerChannel(cid))
            except Exception:
                try:
                    async for d in client.iter_dialogs():
                        if d.id == val or (d.entity and getattr(d.entity, 'id', None) == cid):
                            return d.entity
                except Exception:
                    pass
            return None
        elif kind == "invite":
            try:
                result = await client(CheckChatInviteRequest(hash=val))
                if result.chat:
                    return result.chat
            except Exception:
                pass
            return None
    except Exception as e:
        print(f"[resolve_entity] Error: {e}")
        return None
    return None

entity_cache = {}

async def resolve_entity_cached(c, ref):
    phone = getattr(getattr(c, 'session', None), 'phone', None) or str(id(c))
    store = entity_cache.setdefault(str(phone), {})
    key = str(ref)
    hit = store.get(key)
    if hit and hit[1] > time.time():
        return hit[0]
    ent = await resolve_entity(c, ref)
    if ent:
        store[key] = (ent, time.time() + 1800)
    return ent

# ==========================================================
#  PARSING
# ==========================================================

POST_RE = re.compile(r"(?:https?://)?t\.me/(?:c/(\d+)/(\d+)|([A-Za-z0-9_]{4,})/(\d+))", re.I)
INVITE_RE = re.compile(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)", re.I)

def parse_post_url(url):
    m = POST_RE.search(url.strip())
    if not m:
        return None
    if m.group(1):
        return ("c", int(m.group(1))), int(m.group(2))
    return ("username", m.group(3)), int(m.group(4))

def parse_join_target(text):
    u = text.strip()
    m = INVITE_RE.search(u)
    if m:
        return ("invite", m.group(1))
    m = re.match(r"(?:https?://)?t\.me/@?([A-Za-z0-9_]{3,})/?$", u, re.I)
    if m:
        return ("username", m.group(1))
    if u.startswith("@") and len(u) > 3:
        return ("username", u[1:])
    if re.fullmatch(r"-?\d+", u):
        return ("id", int(u))
    return None

# ==========================================================
#  CAMPAIGN WORKERS
# ==========================================================

RANDOM_EMOJIS = ["👍", "❤️", "🔥", "🎉", "👏", "😍", "💯", "🤩", "🙏", "⚡"]

async def get_allowed_reactions(c, ent):
    try:
        full = await c(GetFullChannelRequest(ent))
        av = getattr(full.full_chat, 'available_reactions', None)
        if av is None:
            return None
        if isinstance(av, ChatReactionsAll):
            return None
        if isinstance(av, ChatReactionsNone):
            return []
        if isinstance(av, ChatReactionsSome):
            return list(av.reactions)
    except Exception:
        return None
    return None

async def do_react(c, ent, msg_id, emoji):
    if emoji and emoji.lower() in ("random", "rand", "r", "🍀"):
        emoji = random.choice(RANDOM_EMOJIS)
    emoji = (emoji or "👍").strip()

    async def attempt(react_obj):
        try:
            if hasattr(c, 'send_reaction'):
                await c.send_reaction(ent, msg_id, reaction=react_obj)
            else:
                await c(SendReactionRequest(
                    peer=ent,
                    msg_id=msg_id,
                    reaction=[react_obj],
                    add_to_recent=True
                ))
            return True, None
        except ReactionInvalidError:
            return False, "reaction not allowed on this post"
        except Exception as ex:
            return False, f"{type(ex).__name__}: {str(ex)[:60]}"

    doc_id = PremiumEmojis.REACTION_EMOJIS.get(emoji)
    if doc_id:
        ok, err = await attempt(ReactionCustomEmoji(document_id=int(doc_id)))
        if ok:
            return True, None

    ok, err = await attempt(ReactionEmoji(emoticon=emoji))
    if ok:
        return True, None

    allowed = await get_allowed_reactions(c, ent)
    if allowed == []:
        return False, "reactions are DISABLED in this chat"
    if allowed:
        custom_ids = [r.document_id for r in allowed if getattr(r, 'document_id', None)]
        std = [r.emoticon for r in allowed if getattr(r, 'emoticon', None)]
        if custom_ids:
            ok, err = await attempt(ReactionCustomEmoji(document_id=custom_ids[0]))
            if ok:
                return True, None
        if std:
            pick = random.choice(std)
            ok, err = await attempt(ReactionEmoji(emoticon=pick))
            if ok:
                return True, f"(auto-used allowed emoji {pick})"

    return False, err or "reaction rejected by Telegram"

async def do_vote(c, ent, msg_id, btn_index, btn_text):
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg or not msg.buttons:
            return False, "no inline buttons on this post"

        btn = None
        idx = 1
        for row in msg.buttons:
            for b in row:
                if (btn_index is not None and idx == btn_index) or \
                   (btn_text and btn_text.lower() in (b.text or "").lower()):
                    btn = b
                    break
                idx += 1
            if btn:
                break
        if btn is None:
            btn = msg.buttons[0][0]

        try:
            await btn.click()
        except (asyncio.TimeoutError, TelethonTimeoutError):
            await c(GetBotCallbackAnswerRequest(peer=ent, msg_id=msg_id, data=btn.data))
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

async def do_poll_vote(c, ent, msg_id, poll_options):
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg or not msg.poll:
            return False, "this post is not a poll"
        answers = msg.poll.poll.answers
        opts = []
        for i in poll_options:
            if i < 0 or i >= len(answers):
                return False, f"option {i} out of range (0-{len(answers)-1})"
            opts.append(answers[i].option)
        await c(SendVoteRequest(peer=ent, msg_id=msg_id, options=opts))
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

async def do_view(c, ent, msg_id):
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if msg:
            await c.send_read_acknowledge(ent, msg)
            return True, None
        return False, "message not found"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

async def do_join_channel(c, target):
    kind, val = target
    try:
        if kind == "invite":
            try:
                await c(ImportChatInviteRequest(val))
                return True, None
            except UserAlreadyParticipantError:
                return True, None
            except (InviteHashExpiredError, InviteHashInvalidError, InviteHashEmptyError):
                return False, "invite link expired/invalid"

        if kind == "username":
            uname = val if val.startswith("@") else "@" + val
            try:
                await c(JoinChannelRequest(uname))
                return True, None
            except UserAlreadyParticipantError:
                return True, None
            except ChannelPrivateError:
                return False, "channel is private — invite link required"

        if kind == "id":
            ent = await resolve_entity(c, target)
            if not ent:
                return False, "could not resolve chat id"
            try:
                await c(JoinChannelRequest(ent))
                return True, None
            except UserAlreadyParticipantError:
                return True, None
            except Exception as e:
                if "username" in str(e).lower():
                    return False, "try using @username instead"
                return False, f"{type(e).__name__}: {str(e)[:60]}"

        return False, "unknown target type"
    except FloodWaitError as e:
        await asyncio.sleep(min(e.seconds, 60))
        return False, f"flood wait {e.seconds}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

async def do_join_request(c, target):
    kind, val = target
    if kind == "invite":
        try:
            await c(ImportChatInviteRequest(val))
            return True, None
        except UserAlreadyParticipantError:
            return True, None
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:60]}"
    return await do_join_channel(c, target)

async def do_leave_channel(c, target):
    try:
        kind, val = target
        if kind == "invite":
            return False, "cannot leave via invite link"
        entity = await resolve_entity(c, target)
        if entity:
            await c(LeaveChannelRequest(entity))
            return True, None
        return False, "chat not found"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

async def do_dm(c, target, text):
    try:
        kind, val = target
        if kind == "invite":
            return False, "DM target must be @username or user id"
        entity = await c.get_entity(val)
        await c.send_message(entity, text)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"

# ==========================================================
#  CAMPAIGN EXECUTION
# ==========================================================

async def get_channel_info_for_campaign(uid, post_ref, target=None):
    accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
    if not accs:
        return None
    first_acc = await get_client(accs[0])
    if not first_acc:
        return None
    try:
        if post_ref:
            if await resolve_entity_cached(first_acc, post_ref):
                return True
        if target:
            if await resolve_entity_cached(first_acc, target):
                return True
    except Exception as e:
        print(f"[channel_info] Error: {e}")
    return None

async def run_campaign(uid, action, opts):
    campaign_id = f"{uid}_{int(time.time())}"
    count = int(opts.get("count", 0))
    if count <= 0:
        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
    else:
        accs = (get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))[:count]

    if not accs:
        return 0, ["No accounts found or limit reached."]

    random.shuffle(accs)
    st = get_settings(uid)
    ok, fail = 0, []

    post_ref = opts.get("post_ref")
    msg_id = opts.get("msg_id")
    target = opts.get("target")
    emoji = opts.get("emoji")
    bi, bt = opts.get("btn_index"), opts.get("btn_text")
    poll_options = opts.get("poll_options", [])
    if isinstance(poll_options, str):
        poll_options = [int(x.strip()) for x in poll_options.split(',') if x.strip().isdigit()]
    join_target = opts.get("join_target")

    campaign_info = {
        'id': campaign_id, 'owner': uid, 'action': action, 'opts': opts,
        'started': time.time(), 'total': len(accs), 'processed': 0, 'status': 'running'
    }
    active_campaigns[campaign_id] = campaign_info
    running_campaigns[campaign_id] = campaign_info

    try:
        for i, acc in enumerate(accs):
            if active_campaigns.get(campaign_id, {}).get('stopped'):
                fail.append(f"Campaign stopped at {i} accounts")
                break

            try:
                c = await get_client(acc)
                if c is None:
                    fail.append(f"{acc['phone']}: Session expired")
                    continue

                if join_target:
                    joined, jerr = await do_join_channel(c, join_target)
                    if not joined:
                        fail.append(f"{acc['phone']}: Join failed — {jerr}")
                        continue
                    await asyncio.sleep(random.uniform(1.0, 2.0))

                current_ent = None
                if post_ref:
                    current_ent = await resolve_entity_cached(c, post_ref)
                    if not current_ent and target:
                        current_ent = await resolve_entity_cached(c, target)

                if post_ref and current_ent is None:
                    if post_ref[0] == "username":
                        join_target_public = ("username", post_ref[1])
                        joined, jerr = await do_join_channel(c, join_target_public)
                        if joined:
                            current_ent = await resolve_entity_cached(c, post_ref)
                    elif post_ref[0] == "id" and post_ref[1] > 0:
                        join_target_id = ("id", post_ref[1])
                        joined, jerr = await do_join_channel(c, join_target_id)
                        if joined:
                            current_ent = await resolve_entity_cached(c, post_ref)

                if post_ref and current_ent is None:
                    fail.append(f"{acc['phone']}: Post not accessible")
                    continue

                if action in ("react", "react_vote", "react_vote_view"):
                    if action == "react_vote_view":
                        await do_view(c, current_ent, msg_id)
                        await asyncio.sleep(random.uniform(0.5, 1.5))

                    success, rerr = await do_react(c, current_ent, msg_id, emoji)
                    if not success:
                        fail.append(f"{acc['phone']}: Reaction failed — {rerr}")
                        continue

                    if action != "react":
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        vsuccess, verr = await do_vote(c, current_ent, msg_id, bi, bt)
                        if not vsuccess:
                            fail.append(f"{acc['phone']}: Vote failed — {verr}")
                            continue

                elif action == "vote":
                    vsuccess, verr = await do_vote(c, current_ent, msg_id, bi, bt)
                    if not vsuccess:
                        fail.append(f"{acc['phone']}: Vote failed — {verr}")
                        continue

                elif action == "poll_vote":
                    psuccess, perr = await do_poll_vote(c, current_ent, msg_id, poll_options)
                    if not psuccess:
                        fail.append(f"{acc['phone']}: Poll vote failed — {perr}")
                        continue

                elif action == "view":
                    vok, verr = await do_view(c, current_ent, msg_id)
                    if not vok:
                        fail.append(f"{acc['phone']}: View failed — {verr}")
                        continue

                elif action == "join":
                    if target:
                        jok, jerr = await do_join_channel(c, target)
                        if not jok:
                            fail.append(f"{acc['phone']}: Join failed — {jerr}")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue

                elif action == "join_request":
                    if target:
                        jok, jerr = await do_join_request(c, target)
                        if not jok:
                            fail.append(f"{acc['phone']}: Join request failed — {jerr}")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue

                elif action == "leave":
                    if target:
                        lok, lerr = await do_leave_channel(c, target)
                        if not lok:
                            fail.append(f"{acc['phone']}: Leave failed — {lerr}")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue

                elif action == "dm":
                    if target:
                        dok, derr = await do_dm(c, target, opts.get("dm_text", ""))
                        if not dok:
                            fail.append(f"{acc['phone']}: DM failed — {derr}")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue

                ok += 1
                campaign_info['processed'] = ok + len(fail)

            except FloodWaitError as e:
                fail.append(f"{acc['phone']}: Flood wait {e.seconds}s")
                await asyncio.sleep(min(e.seconds, 30))
            except Exception as e:
                fail.append(f"{acc['phone']}: {type(e).__name__}: {str(e)[:50]}")

            await asyncio.sleep(random.uniform(st["delay_min"], st["delay_max"]))

    finally:
        campaign_info['status'] = 'completed'
        campaign_info['ended'] = time.time()
        campaign_info['ok'] = ok
        campaign_info['failed'] = len(fail)

        campaigns.append({
            "owner": uid, "action": action, "ok": ok, "fail": len(fail),
            "time": time.strftime("%d-%m %H:%M")
        })
        save_campaigns()

        campaign_history.append({
            "owner": uid, "action": action, "ok": ok, "fail": len(fail),
            "time": time.strftime("%d-%m %H:%M"),
            "total": len(accs),
            "duration": campaign_info['ended'] - campaign_info['started'],
            "campaign_id": campaign_id
        })
        save_campaign_history()

        active_campaigns.pop(campaign_id, None)
        running_campaigns.pop(campaign_id, None)

    return ok, fail

# ==========================================================
#  CAMPAIGN CONTROL
# ==========================================================

def stop_campaign(campaign_id):
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['stopped'] = True
        return True
    return False

def get_running_campaigns():
    return list(running_campaigns.values())

async def scheduler_loop(bot):
    while True:
        now = time.time()
        for s in [x for x in scheduled if x["run_at"] <= now]:
            scheduled.remove(s)
            save_scheduled()
            try:
                ok, fail = await run_campaign(s["owner"], s["action"], s["opts"])
                txt = (f"⏰ {fancy('SCHEDULED CAMPAIGN COMPLETED')}\n"
                       f"Action: `{s['action']}`\n✅ Success: {ok}\n❌ Failed: {len(fail)}")
                if fail:
                    txt += "\n" + "\n".join(f"· {f}" for f in fail[:10])
                await bot.send_message(s["owner"], txt, parse_mode="md")
            except Exception as e:
                print(f"[scheduler] {e}")
        await asyncio.sleep(5)

# ==========================================================
#  BOT SETUP
# ==========================================================

bot = TelegramClient(
    os.path.join(config.SESSIONS_DIR, "control_bot"),
    config.API_ID, config.API_HASH
).start(bot_token=config.BOT_TOKEN)

ACTIONS = [
    ("react", f"{PremiumEmojis.STAR} React"),
    ("vote", f"{PremiumEmojis.VOTE} Vote"),
    ("poll_vote", f"{PremiumEmojis.CHART} Poll Vote"),
    ("react_vote", f"{PremiumEmojis.STAR} React + Vote"),
    ("view", f"{PremiumEmojis.SEARCH} View"),
    ("react_vote_view", f"{PremiumEmojis.STAR} React + Vote + View"),
    ("join", f"{PremiumEmojis.JOIN} Join Channel"),
    ("join_request", f"{PremiumEmojis.REQUEST} Join Request"),
    ("leave", f"{PremiumEmojis.CANCEL} Leave Channel"),
    ("dm", f"{PremiumEmojis.SPEAKER} DM"),
]

MAIN_MENU = [
    [styled_btn(f"{PremiumEmojis.ID} My Account", b"myacc", "primary"),
     styled_btn(f"{PremiumEmojis.CONNECT} Add Account", b"add", "success")],
    [styled_btn(f"{PremiumEmojis.CREATE} New Campaign", b"camp", "primary"),
     styled_btn(f"{PremiumEmojis.CHART} My Campaigns", b"mycamp", "success")],
    [styled_btn(f"{PremiumEmojis.CLOCK} Running", b"running", "primary"),
     styled_btn(f"{PremiumEmojis.STATS} My Status", b"mystat", "success")],
    [styled_btn(f"{PremiumEmojis.SETTINGS} Settings", b"set", "primary"),
     styled_btn(f"{PremiumEmojis.ADMIN} Owner Panel", b"owner_panel", "danger")],
    [styled_btn(f"{PremiumEmojis.CANCEL} Leave Channel", b"leave_menu", "danger"),
     Button.inline(f"{PremiumEmojis.SEARCH} Help", b"help")],
    [styled_btn(f"{PremiumEmojis.CLEAR} Remove Account", b"remove_acc", "danger")],
    [styled_btn(f"{PremiumEmojis.LIST} List Users", b"list_users", "primary")],
]

def menu_text(uid):
    my = len(my_accounts(uid))
    limit = get_user_limit(uid)
    limit_text = "Unlimited" if is_owner(uid) else (f"{limit}" if is_admin(uid) else "0")
    if is_admin(uid) and not is_owner(uid):
        my = len(get_admin_accounts(uid))

    text = (f"{PremiumEmojis.CROWN} **╔═══ {fancy('VOTEFLOW BOT')} ═══╗**\n\n"
            f"{PremiumEmojis.STATS} **{fancy('Your Stats')}:**\n"
            f"┌──────────────────────┐\n"
            f"│ Your Accounts: **{my}**\n"
            f"│ Your Limit: **{limit_text}**\n")

    if is_admin(uid):
        text += f"│ Total Bot Accounts: **{get_total_accounts()}**\n"

    text += (f"└──────────────────────┘\n\n"
             f"{PremiumEmojis.LOCK} **Access:** **{'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}**\n")

    if is_owner(uid):
        text += (f"{PremiumEmojis.CHART} **Global Stats:**\n"
                 f"Total Accounts: **{get_total_accounts()}**\n"
                 f"Running Campaigns: **{len(get_running_campaigns())}**\n"
                 f"Total Users: **{len(set(a.get('owner') for a in accounts))}**\n")

    return text

def no_access():
    return f"{PremiumEmojis.ALERT} **{fancy('ACCESS DENIED')}**\nOnly Owner/Admins can run campaigns."

# ==========================================================
#  ENHANCED CHECK STATUS FUNCTION
# ==========================================================

async def check_user_accounts(uid):
    user_accs = [a for a in accounts if a.get("owner") == uid]
    total = len(user_accs)
    active, expired = [], []
    
    for acc in user_accs:
        c = await get_client(acc)
        if c is None:
            expired.append(acc)
        else:
            try:
                await c.get_me()
                active.append(acc)
            except Exception:
                expired.append(acc)
    
    return {
        'total': total,
        'active': active,
        'active_count': len(active),
        'expired': expired,
        'expired_count': len(expired),
        'all_accounts': user_accs
    }

# ==========================================================
#  COMMANDS
# ==========================================================

@bot.on(events.NewMessage(pattern="^/(start|menu|help)$"))
async def cmd_start(e):
    reset(e.sender_id)
    await e.reply(menu_text(e.sender_id), buttons=MAIN_MENU, parse_mode="md")

@bot.on(events.NewMessage(pattern="^/me$"))
async def cmd_me(e):
    uid = e.sender_id
    total_accs = len(get_admin_accounts(uid)) if is_admin(uid) else len(my_accounts(uid))
    await e.reply(f"{PremiumEmojis.ID} **{fancy('My Profile')}**\n"
                  f"ID: `{uid}`\n"
                  f"Access: {'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}\n"
                  f"Accounts: {total_accs}\n"
                  f"Limit: {get_user_limit(uid)}", parse_mode="md")

@bot.on(events.NewMessage(pattern="^/check(?:\s+(\d+))?$"))
async def cmd_check(e):
    uid = e.sender_id
    
    target_uid = None
    if e.pattern_match.group(1):
        target_uid = int(e.pattern_match.group(1))
        if not is_owner(uid):
            return await e.reply("⛔ Only Owner can check other users!", parse_mode="md")
    else:
        target_uid = uid
        if not is_admin(uid):
            return await e.reply("⛔ Admin access required!", parse_mode="md")
    
    try:
        user_entity = await bot.get_entity(target_uid)
        user_name = user_entity.first_name or "Unknown"
    except:
        user_name = "Unknown"
    
    await e.reply(f"🔍 **{fancy('CHECKING ACCOUNTS')}**\n👤 User: {user_name} (`{target_uid}`)\n⏳ Please wait...", parse_mode="md")
    
    result = await check_user_accounts(target_uid)
    
    lines = [
        f"📊 **{fancy('ACCOUNT STATUS REPORT')}**",
        f"👤 User: **{user_name}** (`{target_uid}`)",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📌 **Total Accounts:** {result['total']}",
        f"🟢 **Active Accounts:** {result['active_count']}",
        f"🔴 **Expired/Failed:** {result['expired_count']}",
        f"━━━━━━━━━━━━━━━━━━━━"
    ]
    
    if result['active']:
        lines.append(f"\n✅ **Active Accounts ({len(result['active'])}):**")
        for acc in result['active']:
            lines.append(f"  🟢 `{acc['phone']}` — {acc.get('name', 'Unknown')}")
    
    if result['expired']:
        lines.append(f"\n❌ **Expired Accounts ({len(result['expired'])}):**")
        for acc in result['expired']:
            lines.append(f"  🔴 `{acc['phone']}` — {acc.get('name', 'Unknown')}")
    
    if result['total'] == 0:
        lines.append("\n⚠️ No accounts found for this user.")
    
    await e.edit("\n".join(lines), parse_mode="md")

@bot.on(events.NewMessage(pattern="^/list$"))
async def cmd_list(e):
    uid = e.sender_id
    
    if not is_owner(uid):
        return await e.reply("⛔ Owner Only! This command shows all bot users.", parse_mode="md")
    
    await e.reply(f"📋 **{fancy('LISTING ALL USERS')}**\n⏳ Fetching account data...", parse_mode="md")
    
    user_accounts = {}
    for acc in accounts:
        owner = acc.get('owner')
        if owner:
            if owner not in user_accounts:
                user_accounts[owner] = []
            user_accounts[owner].append(acc)
    
    if not user_accounts:
        return await e.edit("📋 No users found. No accounts added yet.", parse_mode="md")
    
    lines = [
        f"📋 **{fancy('USER ACCOUNT LIST')}**",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Total Users: **{len(user_accounts)}**",
        f"Total Accounts: **{len(accounts)}**",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    for owner_id, acc_list in user_accounts.items():
        try:
            user_entity = await bot.get_entity(owner_id)
            user_name = user_entity.first_name or "Unknown"
        except:
            user_name = "Unknown"
        
        result = await check_user_accounts(owner_id)
        role = "👑 Owner" if is_owner(owner_id) else "✅ Admin" if is_admin(owner_id) else "👤 User"
        
        lines.append(f"**{user_name}** `{owner_id}`")
        lines.append(f"  {role} | Accounts: {result['total']} | 🟢{result['active_count']} 🔴{result['expired_count']}")
        
        if result['active']:
            lines.append(f"  ✅ Active:")
            for acc in result['active'][:10]:
                lines.append(f"    🟢 `{acc['phone']}` — {acc.get('name', 'Unknown')}")
            if len(result['active']) > 10:
                lines.append(f"    ... and {len(result['active']) - 10} more")
        
        if result['expired']:
            lines.append(f"  ❌ Expired:")
            for acc in result['expired'][:10]:
                lines.append(f"    🔴 `{acc['phone']}` — {acc.get('name', 'Unknown')}")
            if len(result['expired']) > 10:
                lines.append(f"    ... and {len(result['expired']) - 10} more")
        
        if result['total'] == 0:
            lines.append(f"  ⚠️ No accounts")
        
        lines.append("")
    
    response = "\n".join(lines)
    if len(response) > 4000:
        chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
        await e.edit(chunks[0], parse_mode="md")
        for chunk in chunks[1:]:
            await e.reply(chunk, parse_mode="md")
    else:
        await e.edit(response, parse_mode="md")

@bot.on(events.NewMessage(pattern="^/checkall$"))
async def cmd_checkall(e):
    uid = e.sender_id
    
    if not is_owner(uid):
        return await e.reply("⛔ Owner Only!", parse_mode="md")
    
    await e.reply(f"🔍 **{fancy('CHECKING ALL ACCOUNTS')}**\n⏳ This may take a while...", parse_mode="md")
    
    total = len(accounts)
    active_count = 0
    expired_count = 0
    expired_accounts = []
    user_stats = {}
    
    for acc in accounts:
        owner = acc.get('owner')
        if owner not in user_stats:
            user_stats[owner] = {'total': 0, 'active': 0, 'expired': 0}
        user_stats[owner]['total'] += 1
        
        c = await get_client(acc)
        if c is None:
            expired_count += 1
            user_stats[owner]['expired'] += 1
            expired_accounts.append(acc)
        else:
            try:
                await c.get_me()
                active_count += 1
                user_stats[owner]['active'] += 1
            except Exception:
                expired_count += 1
                user_stats[owner]['expired'] += 1
                expired_accounts.append(acc)
    
    lines = [
        f"📊 **{fancy('FULL ACCOUNT STATUS')}**",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📌 **Total Accounts:** {total}",
        f"🟢 **Active:** {active_count}",
        f"🔴 **Expired:** {expired_count}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    lines.append("**👥 Per-User Summary:**")
    for owner_id, stats in user_stats.items():
        try:
            user_entity = await bot.get_entity(owner_id)
            user_name = user_entity.first_name or "Unknown"
        except:
            user_name = "Unknown"
        
        role = "👑 Owner" if is_owner(owner_id) else "✅ Admin" if is_admin(owner_id) else "👤 User"
        lines.append(f"  **{user_name}** `{owner_id}` {role}")
        lines.append(f"    Total: {stats['total']} | 🟢{stats['active']} 🔴{stats['expired']}")
    
    if expired_accounts:
        lines.append(f"\n**🔴 Expired Accounts ({len(expired_accounts)}):**")
        for acc in expired_accounts[:20]:
            owner_name = "Unknown"
            try:
                if acc.get('owner'):
                    user_entity = await bot.get_entity(acc.get('owner'))
                    owner_name = user_entity.first_name or "Unknown"
            except:
                pass
            lines.append(f"  🔴 `{acc['phone']}` — {acc.get('name', 'Unknown')} (Owner: {owner_name})")
        if len(expired_accounts) > 20:
            lines.append(f"  ... and {len(expired_accounts) - 20} more")
    
    response = "\n".join(lines)
    await e.edit(response, parse_mode="md")

@bot.on(events.NewMessage(pattern="^/addadmin(@\w+)?(\s+.*)?$"))
async def cmd_addadmin(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Owner Only!", parse_mode="md")

    target_id, limit = None, 0
    if e.reply_to_msg_id:
        msg = await e.get_reply_message()
        target_id = msg.sender_id
    elif e.pattern_match.group(2):
        args = e.pattern_match.group(2).strip().split()
        if args and args[0].isdigit():
            target_id = int(args[0])
        if len(args) > 1 and args[1].isdigit():
            limit = int(args[1])
        elif len(args) > 1 and args[1].lower() == "unlimited":
            limit = 0

    if target_id is None:
        return await e.reply("Usage: `/addadmin <user_id> <limit>`\n`limit=0` means Unlimited", parse_mode="md")

    admin_exists = next((a for a in admins if a['id'] == target_id), None)
    limit_text = "Unlimited" if limit == 0 else str(limit)
    if admin_exists:
        admin_exists['limit'] = limit
        save_admins()
        return await e.reply(f"✅ Admin limit updated for `{target_id}`: **{limit_text}** accounts", parse_mode="md")

    admins.append({"id": target_id, "limit": limit})
    save_admins()
    await e.reply(f"✅ **`{target_id}` is now Admin!** (Limit: **{limit_text}** accounts)", parse_mode="md")
    try:
        await bot.send_message(target_id, f"🎉 You got **Admin access**! Limit: **{limit_text}** accounts")
    except Exception:
        pass

@bot.on(events.NewMessage(pattern="^/rmadmin(\s+.*)?$"))
async def cmd_rmadmin(e):
    global admins
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Owner Only!", parse_mode="md")

    target_id = None
    if e.reply_to_msg_id:
        msg = await e.get_reply_message()
        target_id = msg.sender_id
    elif e.pattern_match.group(1) and e.pattern_match.group(1).strip().isdigit():
        target_id = int(e.pattern_match.group(1).strip())

    if target_id is None:
        return await e.reply("Usage: `/rmadmin <user_id>`", parse_mode="md")

    admins = [a for a in admins if a.get('id') != target_id]
    save_admins()
    await e.reply(f"🗑️ Admin revoked for `{target_id}`.", parse_mode="md")

@bot.on(events.NewMessage(pattern="^/adminlist$"))
async def cmd_adminlist(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Owner Only!", parse_mode="md")
    if not admins:
        return await e.reply("No admins. Use: `/addadmin <id> <limit>`", parse_mode="md")

    lines = ["👮 **Admins:**"]
    for a in admins:
        try:
            u = await bot.get_entity(a['id'])
            limit_text = "Unlimited" if a.get('limit', 0) == 0 else str(a.get('limit', 0))
            stats = get_admin_usage_stats(a['id'])
            lines.append(f"· `{a['id']}` — {u.first_name} (Limit: {limit_text}) | Campaigns: {stats['total_campaigns']}")
        except Exception:
            limit_text = "Unlimited" if a.get('limit', 0) == 0 else str(a.get('limit', 0))
            lines.append(f"· `{a['id']}` — (Unknown) (Limit: {limit_text})")
    await e.reply("\n".join(lines), parse_mode="md")

@bot.on(events.NewMessage(pattern="^/stop(\s+.*)?$"))
async def cmd_stop(e):
    if not is_admin(e.sender_id):
        return await e.reply("⛔ Admin Only!", parse_mode="md")

    campaign_id = e.pattern_match.group(1)
    if campaign_id:
        campaign_id = campaign_id.strip()
        if stop_campaign(campaign_id):
            await e.reply(f"⏹️ Campaign `{campaign_id}` stopped successfully!", parse_mode="md")
        else:
            await e.reply(f"❌ Campaign `{campaign_id}` not found or already completed.", parse_mode="md")
    else:
        running = get_running_campaigns()
        if not running:
            return await e.reply("No running campaigns.", parse_mode="md")
        lines = ["⏹️ **Running Campaigns:**"]
        for c in running:
            lines.append(f"· `{c['id']}` — {c['action']} ({c['processed']}/{c['total']})")
        lines.append("\nUse `/stop <campaign_id>` to stop")
        await e.reply("\n".join(lines), parse_mode="md")

# ==========================================================
#  CALLBACK ROUTER
# ==========================================================

@bot.on(events.CallbackQuery())
async def cb(e):
    uid = e.sender_id
    data = e.data.decode()
    s = state(uid)

    if data == "menu":
        reset(uid)
        return await e.edit(menu_text(uid), buttons=MAIN_MENU, parse_mode="md")

    if data == "list_users":
        if not is_owner(uid):
            return await e.answer("⛔ Owner Only!", alert=True)
        await cmd_list(e)
        return

    if data.startswith("pickbtn:"):
        idx = int(data[8:])
        s = state(uid)
        btns = s.get("post_btns") or []
        if 1 <= idx <= len(btns):
            s.setdefault("camp_opts", {})
            s["camp_opts"]["btn_index"] = idx
            s["camp_opts"]["btn_text"] = btns[idx - 1].text
            return await e.answer(f"✅ Button {idx} selected: {(btns[idx-1].text or '?')[:30]}")
        return await e.answer("Invalid button", alert=True)

    if data == "react_specific":
        s = state(uid)
        s["step"] = "camp_emoji"
        return await e.edit("😀 **Send the emoji** you want:\n\n"
                            "`👍` `❤️` `🔥` `🎉` `💎` `👑` `😍` `🚀` `☺️`\n"
                            "or type any emoji.\n\n"
                            "💡 Premium custom emoji versions are used automatically "
                            "when the account has Telegram Premium.",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "react_random":
        s = state(uid)
        s.setdefault("camp_opts", {})["emoji"] = "random"
        return await ask_run(e, uid)

    if data == "running":
        running = get_running_campaigns()
        if not running:
            return await e.edit("No running campaigns.", buttons=[[Button.inline("« Back", b"menu")]])
        lines = ["⏱️ **Running Campaigns:**"]
        for c in running:
            progress = f"{c['processed']}/{c['total']}" if c['total'] > 0 else "Processing"
            lines.append(f"· `{c['id'][:8]}` — {c['action']} ({progress})")
        await e.edit("\n".join(lines), buttons=[[Button.inline("« Back", b"menu")]])

    if data == "owner_panel":
        if not is_owner(uid):
            return await e.answer("⛔ Owner Only!", alert=True)
        lines = [f"👑 **{fancy('OWNER PANEL')}**\n"
                 f"Global Accounts: {len(accounts)}\n"
                 f"Users: {len(set(a.get('owner') for a in accounts))}\n"
                 f"Admins: {len(admins)}\n"
                 f"Running Campaigns: {len(get_running_campaigns())}\n"
                 f"Scheduled: {len(scheduled)}"]
        if admins:
            lines.append("\n**Admins:**")
            for a in admins[:10]:
                limit_text = "Unlimited" if a.get('limit', 0) == 0 else str(a.get('limit', 0))
                lines.append(f"· `{a['id']}` (Limit: {limit_text})")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    if data in ("myacc", "profile"):
        result = await check_user_accounts(uid)
        
        lines = [f"🧑‍💼 **{fancy('MY PROFILE')}**\nID: `{uid}`\n"
                 f"Access: **{'👑 Owner' if is_owner(uid) else '✅ Admin' if is_admin(uid) else '👤 User'}**"]
        
        if is_admin(uid):
            accs = get_admin_accounts(uid)
            lines.append(f"📊 Accessible: {len(accs)} | 🟢{result['active_count']} 🔴{result['expired_count']}")
            if accs:
                lines.append("\n**Accounts (sample):**")
                for acc in accs[:15]:
                    status = "🟢" if acc in result['active'] else "🔴"
                    lines.append(f"{status} `{acc['phone']}` — {acc.get('name','?')}")
        else:
            lines.append(f"📊 Accounts: {result['total']} | 🟢{result['active_count']} 🔴{result['expired_count']}")
        
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    if data == "mystat":
        myc = [c for c in campaigns if c["owner"] == uid]
        result = await check_user_accounts(uid)
        lines = [f"📊 **{fancy('MY STATUS')}**"]
        if is_admin(uid):
            lines.append(f"Accessible Accounts: {len(get_admin_accounts(uid))}")
        else:
            lines.append(f"Your Accounts: {result['total']} | 🟢{result['active_count']} 🔴{result['expired_count']}")
        lines.append(f"Campaigns Run: {len(myc)}")
        lines.append(f"Scheduled: {len([x for x in scheduled if x['owner']==uid])}")
        if myc:
            lines.append("\n**Last 5 Campaigns:**")
            for c in myc[-5:]:
                lines.append(f"· `{c['time']}` {c['action']} ✅{c['ok']} ❌{c['fail']}")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    if data == "mycamp":
        myc = [c for c in campaigns if c["owner"] == uid]
        if not myc:
            return await e.edit("📋 No campaigns yet.", buttons=[[Button.inline("« Back", b"menu")]])
        lines = [f"📋 **My Campaigns ({len(myc)})**"]
        for c in myc[-15:]:
            lines.append(f"· `{c['time']}` {c['action']} ✅{c['ok']} ❌{c['fail']}")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    if data == "help":
        return await e.edit(
            f"❓ **{fancy('HELP — VOTEFLOW BOT')}**\n\n"
            "**📌 Quick Start:**\n"
            "1️⃣ Add Accounts (Phone+OTP / Session / Bulk)\n"
            "2️⃣ New Campaign → pick action\n"
            "3️⃣ Bot shows the post & its real buttons → click to select\n"
            "4️⃣ Run!\n\n"
            "**🎯 React:** choose 🎯 Specific or 🎲 Random emoji. Premium custom "
            "emoji is sent automatically when the account is Premium.\n\n"
            "**🗳️ Vote:** bot opens the post and shows its actual inline buttons — "
            "just click one. Works on vote bots (poll-style buttons).\n\n"
            "**🔐 Private channels (ONE campaign does everything):**\n"
            "Send the post link → bot detects it's private → send the invite link "
            "(t.me/+hash) → accounts JOIN first, then React/Vote automatically.\n\n"
            "**📢 Public channels/groups:**\n"
            "Bot automatically tries to join if needed. Works for both reactions and votes.\n\n"
            "**📋 Commands:**\n"
            "🔹 **/start** - Main menu\n"
            "🔹 **/me** - Your profile\n"
            "🔹 **/check [user_id]** - Check account status (Owner: check others)\n"
            "🔹 **/list** - List all users with account stats (Owner only)\n"
            "🔹 **/checkall** - Check all accounts (Owner only)\n"
            "🔹 **/stop** - Stop running campaign\n"
            "🔹 **/addadmin [user_id] [limit]** - Add admin (Owner only)\n"
            "🔹 **/rmadmin [user_id]** - Remove admin (Owner only)\n"
            "🔹 **/adminlist** - List all admins (Owner only)\n\n"
            "**💡 Tips:**\n"
            "• Count `0` = all accounts\n"
            "• Set delay `1-3` in Settings\n"
            "• Run `/check` before campaigns\n"
            "• Use `/list` to see all users and their account status\n"
            "• Use `/checkall` for full account health check",
            parse_mode="md",
            buttons=[[Button.inline("« Back", b"menu")]]
        )

    if data == "add":
        s.clear()
        return await e.edit(f"{PremiumEmojis.CONNECT} **{fancy('ADD ACCOUNT')}**",
                            buttons=[[styled_btn("📱 Phone + OTP", b"add_phone", "primary")],
                                     [styled_btn("🔑 Session String", b"add_string", "primary")],
                                     [styled_btn("📋 Bulk Sessions", b"bulk", "primary")],
                                     [Button.inline("« Back", b"menu")]], parse_mode="md")

    if data == "add_phone":
        s.clear()
        s["step"] = "add_phone_number"
        return await e.edit("📱 **Phone Login**\nSend phone (international):\n`+919876543210`",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "add_string":
        s.clear()
        s["step"] = "add_string_input"
        return await e.edit("🔑 **Session Login**\nSend your session string:",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "bulk":
        s.clear()
        s["step"] = "bulk_input"
        return await e.edit("📋 **Bulk Sessions**\nPaste strings (1 per line) or upload a `.txt` file",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "remove_acc":
        s.clear()
        s["step"] = "remove_input"
        return await e.edit(f"{PremiumEmojis.CLEAR} **{fancy('REMOVE ACCOUNT')}**\nSend phone number:\n`+919876543210`\n\n⚠️ Permanent!",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "set":
        st = get_settings(uid)
        s["step"] = "set"
        return await e.edit(f"⚙️ **{fancy('SETTINGS')}**\nDelay: `{st['delay_min']}`–`{st['delay_max']}` sec\n\nSet new: `min-max` (e.g. `1-3`)",
                            buttons=[[Button.inline("« Back", b"menu")]], parse_mode="md")

    if data == "leave_menu":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s.clear()
        s["step"] = "camp_target"
        s["camp_action"] = "leave"
        return await e.edit("🚪 **Leave Channel**",
                            buttons=[[styled_btn("📂 Show My Chats", b"list_chats", "primary")],
                                     [styled_btn("✍️ Manual", b"leave_manual", "primary")],
                                     [Button.inline("« Cancel", b"menu")]])

    if data == "leave_manual":
        s["step"] = "camp_target"
        return await e.edit("🚪 Send @username or chat id:",
                            buttons=[[Button.inline("« Cancel", b"menu")]])

    if data == "list_chats":
        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
        if not accs:
            return await e.edit("❌ Add an account first.", buttons=[[Button.inline("« Back", b"menu")]])
        c = await get_client(accs[0])
        if not c:
            return await e.edit("❌ Account dead.", buttons=[[Button.inline("« Back", b"menu")]])
        dialogs = await c.get_dialogs(limit=25)
        btns = []
        for d in dialogs:
            if d.is_group or d.is_channel:
                btns.append([styled_btn(f"🚪 {d.name[:30]}", f"doleave:{d.id}".encode(), "danger")])
        btns.append([Button.inline("« Cancel", b"menu")])
        return await e.edit("📂 Click to leave:", buttons=btns)

    if data.startswith("doleave:"):
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        chat_id = int(data[8:])
        ok, fail = await run_campaign(uid, "leave", {"target": ("id", chat_id)})
        await e.answer(f"✅ {ok} left, ❌ {len(fail)} failed" if ok else
                       f"❌ Failed: {fail[0][:80] if fail else 'unknown'}", alert=True)
        return

    if data == "camp":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s.clear()
        s["step"] = "camp_action"
        btns = []
        style_cycle = ["primary", "success"]
        for i, (key, label) in enumerate(ACTIONS):
            btns.append([styled_btn(label, f"act:{key}".encode(), style_cycle[i % 2])])
        btns.append([Button.inline("« Back", b"menu")])
        return await e.edit(f"🚀 **{fancy('NEW CAMPAIGN')}**\nSelect action:", buttons=btns, parse_mode="md")

    if data.startswith("act:"):
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        key = data[4:]
        s.clear()
        s["camp_action"] = key

        if key in ("join", "join_request", "leave", "dm"):
            s["step"] = "camp_target"
            hints = {
                "join": f"{PremiumEmojis.JOIN} **Join Channel**\n\nSend channel link or username:\n`@channel`\n`https://t.me/channel`\n`https://t.me/+invite_hash`",
                "join_request": f"{PremiumEmojis.REQUEST} **Join Request**\n\nSend channel invite link:\n`https://t.me/+invite_hash`",
                "leave": f"{PremiumEmojis.CANCEL} **Leave**\nSend channel link or username",
                "dm": f"{PremiumEmojis.SPEAKER} **DM**\nSend username or user id",
            }
            return await e.edit(hints[key], buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

        s["step"] = "camp_post"
        return await e.edit(
            f"{PremiumEmojis.CHANNEL} **{fancy('POST LINK')}**\n\n"
            "Send the post URL:\n"
            "`https://t.me/channel/123` (public)\n"
            "`https://t.me/c/1234567890/123` (private)\n\n"
            "🔐 **Private channel?** Send the post link — the bot will then ask "
            "for the invite link, and accounts will **JOIN + React/Vote in one go**.\n\n"
            "📢 **Public channel/group?** Accounts will try to join automatically "
            "if needed.",
            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "run_now":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s = state(uid)
        await e.edit("⏳ Running campaign...")
        ok, fail = await run_campaign(uid, s["camp_action"], s["camp_opts"])
        lines = [f"✅ **{fancy('COMPLETED')}** — {ok} success, {len(fail)} failed"]
        lines += [f"· {f}" for f in fail[:15]]
        reset(uid)
        return await e.edit("\n".join(lines), buttons=[[Button.inline("« Menu", b"menu")]],
                            parse_mode="md")

    if data == "do_schedule":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s = state(uid)
        scheduled.append({"run_at": time.time() + s["sched_delay"], "owner": uid,
                          "action": s["camp_action"], "opts": s["camp_opts"]})
        save_scheduled()
        reset(uid)
        return await e.edit("📅 **Scheduled!**", buttons=[[Button.inline("« Menu", b"menu")]])

# ==========================================================
#  TEXT STEP HANDLER
# ==========================================================

@bot.on(events.NewMessage())
async def steps(e):
    uid = e.sender_id
    if e.text and e.text.startswith("/"):
        return

    s = state(uid)
    step = s.get("step")
    if not step:
        return

    text = (e.text or "").strip()

    if step == "add_phone_number":
        if not re.fullmatch(r"\+\d{6,15}", text):
            return await e.reply("❌ Invalid format. Example: `+919876543210`", parse_mode="md")
        s["phone"] = text
        client = TelegramClient(os.path.join(config.SESSIONS_DIR, text.lstrip("+")),
                                config.API_ID, config.API_HASH)
        await client.connect()
        sent = await client.send_code_request(text)
        s["phone_code_hash"] = sent.phone_code_hash
        s["client"] = client
        s["step"] = "add_phone_otp"
        return await e.reply("🔢 Code sent! Send OTP (e.g. `1 2 3 4 5 6`)")

    if step == "add_phone_otp":
        client = s.get("client")
        if not client:
            reset(uid)
            return await e.reply("Session expired. Try /start")
        try:
            await client.sign_in(phone=s["phone"], code=text.replace(" ", ""),
                                 phone_code_hash=s["phone_code_hash"])
        except PhoneCodeInvalidError:
            return await e.reply("❌ Invalid code. Try again:")
        except PhoneCodeExpiredError:
            reset(uid)
            return await e.reply("❌ Code expired. /start")
        except SessionPasswordNeededError:
            s["step"] = "add_phone_password"
            return await e.reply("🔒 2FA enabled. Send password:")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(f"✅ Added `{acc['phone']}` — {acc['name']}",
                             buttons=MAIN_MENU, parse_mode="md")

    if step == "add_phone_password":
        client = s.get("client")
        try:
            await client.sign_in(password=text)
        except Exception as ex:
            return await e.reply(f"❌ Wrong password: {ex}\nTry again:")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(f"✅ Added `{acc['phone']}`", buttons=MAIN_MENU, parse_mode="md")

    if step == "add_string_input":
        try:
            acc = await validate_session_string(text, uid)
        except Exception as ex:
            return await e.reply(f"❌ {ex}\nSend a valid string:")
        reset(uid)
        return await e.reply(f"✅ Added `{acc['phone']}` — {acc['name']}",
                             buttons=MAIN_MENU, parse_mode="md")

    if step == "bulk_input":
        strings = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
        added, bad = 0, []
        for ss in strings:
            try:
                await validate_session_string(ss, uid)
                added += 1
            except Exception as ex:
                bad.append(str(ex)[:60])
        reset(uid)
        msg = f"✅ {added} sessions added."
        if bad:
            msg += f"\n❌ {len(bad)} failed:\n" + "\n".join(f"· {b}" for b in bad[:10])
        return await e.reply(msg, buttons=MAIN_MENU, parse_mode="md")

    if step == "remove_input":
        phone = text if text.startswith("+") else "+" + text
        acc = next((a for a in my_accounts(uid) if a["phone"] == phone), None)
        if not acc:
            return await e.reply("❌ Account not found.")
        c = clients.pop(phone, None)
        if c:
            await c.disconnect()
        accounts.remove(acc)
        save_accounts()
        p = os.path.join(config.SESSIONS_DIR, phone.lstrip("+") + ".session")
        if os.path.exists(p):
            os.remove(p)
        reset(uid)
        return await e.reply(f"🗑️ Removed `{phone}`", buttons=MAIN_MENU, parse_mode="md")

    if step == "set":
        m = re.fullmatch(r"([\d.]+)\s*-\s*([\d.]+)", text)
        if not m or float(m.group(1)) > float(m.group(2)):
            return await e.reply("❌ Format: `1-3` (min-max seconds)", parse_mode="md")
        st = get_settings(uid)
        st["delay_min"], st["delay_max"] = float(m.group(1)), float(m.group(2))
        save_settings()
        reset(uid)
        return await e.reply(f"✅ Delay set: `{st['delay_min']}`–`{st['delay_max']}`s",
                             buttons=MAIN_MENU, parse_mode="md")

    if step in ("camp_post", "camp_private_invite", "camp_count", "camp_emoji",
                "camp_btn", "camp_target", "camp_dm_text", "sched_time",
                "camp_poll_options", "camp_channel_target"):
        if not is_admin(uid):
            reset(uid)
            return await e.reply(no_access())
        if "camp_opts" not in s:
            s["camp_opts"] = {}

    if step == "camp_post":
        parsed = parse_post_url(text)
        if not parsed:
            return await e.reply(
                "❌ Invalid post URL.\n\nFormat:\n`https://t.me/channel/123` (public)\n"
                "`https://t.me/c/1234567890/123` (private)",
                parse_mode="md")

        s["camp_opts"]["post_ref"] = parsed[0]
        s["camp_opts"]["msg_id"] = parsed[1]
        s.pop("post_btns", None)
        s.pop("post_poll", None)

        if parsed[0][0] == "c":
            s["step"] = "camp_private_invite"
            return await e.reply(
                f"🔐 **{fancy('PRIVATE CHANNEL DETECTED')}**\n\n"
                "This post is inside a private channel. Accounts must be members "
                "to react/vote.\n\n"
                "📩 **Send the channel's invite link** now:\n"
                "`https://t.me/+AbCdEfGh123` or `https://t.me/joinchat/XXXX`\n\n"
                "➡️ Accounts will **JOIN first, then React/Vote** in one campaign.\n"
                "💡 If your accounts are already members, type `skip`.",
                buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
        preview, btn_rows = "", []
        if accs:
            c0 = await get_client(accs[0])
            if c0:
                ent0 = await resolve_entity_cached(c0, parsed[0])
                if ent0:
                    try:
                        m0 = await c0.get_messages(ent0, ids=parsed[1])
                        if m0:
                            preview = f"\n\n📝 Post: {(m0.text or '(media)')[:80]}..."
                            if getattr(m0, "buttons", None):
                                s["post_btns"] = [b for row in m0.buttons for b in row]
                                preview += (f"\n🗳️ **{len(s['post_btns'])} inline buttons "
                                            f"found — click to select:**")
                                for i, b in enumerate(s["post_btns"], 1):
                                    btn_rows.append([styled_btn(
                                        f"{i}. {(b.text or '?')[:25]}",
                                        f"pickbtn:{i}".encode(), "success")])
                            elif getattr(m0, "poll", None):
                                s["post_poll"] = [a.text for a in m0.poll.poll.answers]
                                preview += "\n📊 **Poll detected!** Options:"
                                for i, a in enumerate(s["post_poll"]):
                                    preview += f"\n  `{i}`. {a}"
                        else:
                            preview = "\n\n⚠️ Post not found — check the message ID."
                    except Exception as ex:
                        preview = f"\n\n⚠️ Preview error: {str(ex)[:50]}"
                else:
                    preview = "\n\n⚠️ Could not open the post with any account."

        s["step"] = "camp_count"
        total_accs = len(accs)
        btn_rows.append([Button.inline("« Cancel", b"menu")])
        return await e.reply(
            f"🔢 **{fancy('HOW MANY ACCOUNTS?')}**\n\nAvailable: **{total_accs}**\n"
            f"`0` = All available{preview}",
            buttons=btn_rows, parse_mode="md")

    if step == "camp_private_invite":
        if text.lower() in ("skip", "no", "already"):
            s["step"] = "camp_count"
            return await e.reply(
                f"🔢 **{fancy('HOW MANY ACCOUNTS?')}**\n\n"
                f"Available: **{len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))}**\n"
                "`0` = All available\n\n⚠️ Without an invite link, only accounts that are "
                "ALREADY members can react/vote.",
                parse_mode="md")

        m = INVITE_RE.search(text)
        if not m:
            return await e.reply(
                "❌ Invalid invite link. Format:\n`https://t.me/+AbCdEfGh123`\n\n"
                "Or type `skip` if accounts are already members.",
                parse_mode="md")

        s["camp_opts"]["join_target"] = ("invite", m.group(1))
        s["step"] = "camp_count"
        return await e.reply(
            f"✅ **{fancy('JOIN + ACT MODE ENABLED')}**\n\n"
            "During the campaign, every account will:\n"
            "1️⃣ Join the private channel (invite link)\n"
            "2️⃣ Wait for sync\n"
            "3️⃣ React / Vote on the post\n\n"
            f"🔢 **How many accounts?**\n`0` = All available",
            parse_mode="md")

    if step == "camp_count":
        if not text.isdigit():
            return await e.reply("❌ Send a number (e.g. `50`). `0` means all available.", parse_mode="md")
        s["camp_opts"]["count"] = int(text)

        action = s["camp_action"]

        if action in ("join", "join_request", "leave"):
            if "target" not in s["camp_opts"]:
                s["step"] = "camp_target"
                return await e.reply(
                    "📌 **Send channel target:**\n\nUsername: `@channel`\n"
                    "Invite: `https://t.me/+invite_hash`\nID: `-1001234567890`", parse_mode="md")
            return await ask_run(e, uid)

        if action == "dm":
            if "target" not in s["camp_opts"]:
                s["step"] = "camp_target"
                return await e.reply("📩 **Send username or user ID:**\n\n`@username` or `123456789`", parse_mode="md")
            if "dm_text" not in s["camp_opts"]:
                s["step"] = "camp_dm_text"
                return await e.reply("✉️ **Send the DM message** you want to send:", parse_mode="md")
            return await ask_run(e, uid)

        if action in ("react", "react_vote", "react_vote_view"):
            s["step"] = None
            return await e.reply(
                f"😀 **{fancy('REACTION TYPE')}**",
                buttons=[[styled_btn("🎯 Specific Emoji", b"react_specific", "primary")],
                         [styled_btn("🎲 Random Emoji", b"react_random", "success")],
                         [Button.inline("« Cancel", b"menu")]])

        if action == "vote":
            if s["camp_opts"].get("btn_index") or s["camp_opts"].get("btn_text"):
                return await ask_run(e, uid)
            s["step"] = "camp_btn"
            return await e.reply(
                "🗳️ Send the button **number** or **text**:\n`1` / `Vote Now`\n\n"
                "💡 (If buttons were shown above, just click one.)", parse_mode="md")

        if action == "poll_vote":
            s["step"] = "camp_poll_options"
            return await e.reply(
                "📊 Send poll option numbers (comma separated):\n`0,1,2`\n(0 = first option)",
                parse_mode="md")

        return await ask_run(e, uid)

    if step == "camp_emoji":
        if not text.strip():
            return await e.reply("❌ Send an emoji!")
        s["camp_opts"]["emoji"] = text.strip()
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            if s["camp_opts"].get("btn_index") or s["camp_opts"].get("btn_text"):
                return await ask_run(e, uid)
            s["step"] = "camp_btn"
            return await e.reply("🗳️ Button number/text: `1` / `Vote Now`", parse_mode="md")
        return await ask_run(e, uid)

    if step == "camp_btn":
        if text.isdigit():
            s["camp_opts"]["btn_index"] = int(text)
            s["camp_opts"]["btn_text"] = None
        else:
            s["camp_opts"]["btn_index"] = None
            s["camp_opts"]["btn_text"] = text
        return await ask_run(e, uid)

    if step == "camp_poll_options":
        options = [x.strip() for x in text.split(',') if x.strip().isdigit()]
        if not options:
            return await e.reply("❌ Invalid. Use: `0,1,2`\n(0 = first option, 1 = second…)", parse_mode="md")
        s["camp_opts"]["poll_options"] = [int(x) for x in options]
        return await ask_run(e, uid)

    if step == "camp_target":
        parsed = parse_join_target(text)
        if not parsed:
            return await e.reply(
                "❌ Invalid target.\n\nFormat:\n`@channel`\n`https://t.me/+invite_hash`\n"
                "`https://t.me/channel`\n`-1001234567890`", parse_mode="md")

        s["camp_opts"]["target"] = parsed

        if s["camp_action"] == "dm":
            s["step"] = "camp_dm_text"
            return await e.reply("✉️ **Send the DM message** you want to send:", parse_mode="md")

        if s["camp_action"] in ("join", "join_request", "leave"):
            s["step"] = "camp_count"
            total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
            return await e.reply(
                f"🔢 **{fancy('HOW MANY ACCOUNTS?')}**\n\nAvailable: **{total_accs}**\n`0` = All available",
                parse_mode="md")

        return await ask_run(e, uid)

    if step == "camp_dm_text":
        s["camp_opts"]["dm_text"] = text
        s["step"] = "camp_count"
        total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        return await e.reply(
            f"🔢 **{fancy('HOW MANY ACCOUNTS?')}**\n\nAvailable: **{total_accs}**\n`0` = All available",
            parse_mode="md")

    if step == "sched_time":
        m = re.fullmatch(r"(\d+)([mhd])", text.lower())
        if not m:
            return await e.reply("❌ Format: `30m`, `2h`, `1d`", parse_mode="md")
        mult = {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
        s["sched_delay"] = int(m.group(1)) * mult
        label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
        return await e.reply(f"📅 **{label}** in **{text}**. Confirm?",
                             buttons=[[styled_btn("✅ Confirm", b"do_schedule", "success")],
                                      [Button.inline("❌ Cancel", b"menu")]])

async def ask_run(e, uid):
    s = state(uid)
    s["step"] = None
    label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
    opts = s.get("camp_opts", {})

    summary = f"🚀 **{fancy('CAMPAIGN READY')}**\n\nAction: **{label}**\n"
    if "post_ref" in opts:
        summary += f"Post ID: `{opts['msg_id']}`\n"
    if "join_target" in opts:
        summary += f"🔐 Auto-Join: `YES (invite link)`\n"
    if "count" in opts:
        count = opts['count']
        total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        if count == 0:
            summary += f"Accounts: **All ({total_accs})**\n"
        else:
            summary += f"Accounts: **{min(count, total_accs)}**\n"
    if "emoji" in opts:
        emoji_display = "🎲 Random" if opts['emoji'].lower() in ("random", "rand", "r", "🍀") else opts['emoji']
        summary += f"Emoji: {emoji_display}\n"
    if opts.get("btn_index") or opts.get("btn_text"):
        summary += f"Button: `{opts.get('btn_index') or opts.get('btn_text')}`\n"
    if "target" in opts:
        summary += f"Target: `{opts['target'][1]}`\n"
    if "dm_text" in opts:
        summary += f"Message: {opts['dm_text'][:60]}\n"
    if "poll_options" in opts:
        summary += f"Poll Options: {opts['poll_options']}\n"

    summary += (f"\n📊 Available Accounts: **{len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))}**")

    await send(e, summary, parse_mode="md")
    await send(e, "▶️ **Run now or schedule?**",
               buttons=[[styled_btn("▶️ Run Now", b"run_now", "success"),
                         styled_btn("📅 Schedule", b"schedule_btn", "primary")],
                        [Button.inline("« Cancel", b"menu")]])

@bot.on(events.CallbackQuery(pattern=b"^schedule_btn$"))
async def sched_btn(e):
    if not is_admin(e.sender_id):
        return await e.answer(no_access(), alert=True)
    s = state(e.sender_id)
    s["step"] = "sched_time"
    await e.edit("📅 **Schedule Time**\n\nSend delay: `30m` / `2h` / `1d`",
                 buttons=[[Button.inline("« Cancel", b"menu")]])

@bot.on(events.NewMessage(func=lambda e: e.document))
async def txt_upload(e):
    s = state(e.sender_id)
    if s.get("step") != "bulk_input":
        return
    fname = (e.document.attributes[0].file_name if e.document.attributes else "") or ""
    if not fname.endswith(".txt"):
        return await e.reply("❌ Only `.txt` files.")
    data = await e.download_media(file=bytes)
    e.text = data.decode("utf-8", errors="ignore")
    await steps(e)

# ==========================================================
#  MAIN
# ==========================================================

async def main():
    load_scheduled()

    # Check and restore accounts if needed
    check_and_restore_on_startup()

    print("[VoteFlow] Preloading accounts...")
    for acc in accounts[:10]:
        try:
            await get_client(acc)
        except Exception as ex:
            print(f"[load] {acc['phone']}: {ex}")

    asyncio.create_task(scheduler_loop(bot))

    print(f"[VoteFlow] Telethon version: {__import__('telethon').__version__}")

    print(f"[VoteFlow] Running. Accounts: {len(accounts)}, Admins: {len(admins)+1}, "
          f"Scheduled: {len(scheduled)}")
    print(f"[VoteFlow] Button colors supported: {HAS_BTN_STYLE} "
          f"(pip install -U Telethon to enable colors)")
    print(f"[VoteFlow] Admin Limits active: {sum(1 for a in admins if a.get('limit', 0) > 0)}")
    print(f"[VoteFlow] Backup directory: {BACKUP_DIR}")
    print(f"[VoteFlow] Auto-restore enabled!")

    await bot.run_until_disconnected()

if __name__ == "__main__":
    bot.loop.run_until_complete(main())
