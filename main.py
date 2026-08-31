import asyncio
import json
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any

from telethon import TelegramClient, events, Button, errors
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, FloodWaitError, UserAlreadyParticipantError,
    ChannelPrivateError, ChatAdminRequiredError, InviteHashInvalidError,
    InviteHashExpiredError, InviteHashEmptyError, UserNotParticipantError,
    ChannelInvalidError
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    ImportChatInviteRequest, SendVoteRequest, GetBotCallbackAnswerRequest,
    CheckChatInviteRequest, GetMessagesRequest
)
from telethon.tl.functions.channels import (
    JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest,
    GetParticipantRequest
)
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.types import (
    PeerChannel, ReactionEmoji, InputPeerChannel,
    MessageEntityTextUrl, Channel, Chat, ChannelParticipant,
    ChannelParticipantBanned, ChannelParticipantCreator,
    ChannelParticipantAdmin, Message, MessageService, ChannelFull
)
from telethon.tl.functions import channels

import config

os.makedirs(config.SESSIONS_DIR, exist_ok=True)
LOCK = threading.Lock()

# ==========================================================
#  PREMIUM EMOJIS
# ==========================================================

class PremiumEmojis:
    VOTE = "🗳️"; JOIN = "➕"; CANCEL = "❌"; MAIN_MENU = "🏠"
    BACK = "🔙"; CREATE = "🚀"; CONNECT = "🔗"; MANAGE = "🛠️"
    ADD_VOTES = "➕"; REMOVE_VOTES = "➖"; LEADERBOARD = "🏆"
    END_GIVEAWAY = "🏁"; ADMIN = "👑"; BROADCAST = "📢"
    STATS = "📊"; SETTINGS = "⚙️"; USERS = "👥"; BACKUP = "💾"
    CLEAR = "🗑️"; CHANNEL = "📡"; NOTIFICATION = "🔔"; CONFIRM = "✅"
    REFRESH = "🔄"; WELCOME = "👋"; FIRE = "🔥"; ARROW = "➡️"
    CHART = "📈"; HEART = "❤️"; ROCKET = "🚀"; CROWN = "👑"
    ERROR = "⚠️"; ENDED = "🏁"; STAR = "⭐"; ID = "🆔"; GIFT = "🎁"
    WINE = "🍷"; SMILE = "🙂"; LOVE = "😍"; LIGHTNING = "⚡"
    POINTER = "👉"; ALERT = "🚨"; CLOWN = "🤡"; SEARCH = "🔍"
    SPEAKER = "🔊"; LINK = "🔗"; CONFETTI = "🎉"; LOCATION = "📍"
    RIGHT = "✔️"; DIAMOND = "💎"; CALENDAR = "📅"; WINNER = "🏅"
    MONEY_BAG = "💰"; CELEBRATE = "🎊"; INBOX = "📥"; LOCK = "🔒"
    SHIELD = "🛡️"; JOIN_CHANNEL = "📨"; JOINED = "✔️"; EXPORT = "📤"
    IMPORT = "📥"; PUBLIC = "🌐"; PRIVATE = "🔐"; REQUEST = "📩"
    STOP = "⏹️"; PAUSE = "⏸️"; RESUME = "▶️"; CLOCK = "⏰"
    GROUP = "👥"; CHANNEL = "📺"; PRIVATE_CHANNEL = "🔏"; DIRECT_JOIN = "⚡"

    REACTION_EMOJIS = {
        "🔥": "6334449730734529256", "❤️": "6237558987978447573",
        "⭐": "6239815031219820750", "💎": "6240003971126139705",
        "👑": "6332246180583447893", "🎉": "6240085923397114865",
        "👍": "6237867138997034625", "😍": "6334437167955188087",
        "🚀": "5188481279963715781", "💯": "6239815031219820750",
        "🤩": "6239815031219820750", "🙌": "6237621707385871360",
        "👏": "6237621707385871360", "💪": "5188481279963715781",
        "✨": "6240085923397114865",
    }

# ==========================================================
#  STORAGE
# ==========================================================

def jload(path, default):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)
        return default
    try:
        with LOCK:
            with open(path) as f:
                return json.load(f)
    except Exception:
        try:
            os.replace(path, path + ".corrupt")
        except Exception:
            pass
        return default

def jsave(path, data):
    tmp = path + ".tmp"
    with LOCK:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)

# Load all data
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

def save_accounts(): jsave(config.ACCOUNTS_FILE, accounts)
def save_admins(): jsave(config.ADMINS_FILE, admins)
def save_settings(): jsave(config.SETTINGS_FILE, settings)
def save_campaigns(): jsave(config.CAMPAIGNS_FILE, campaigns)
def save_campaign_history(): jsave(config.CAMPAIGNS_FILE + "_history", campaign_history)

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
    except Exception as ex:
        print(f"[scheduled] save error: {ex}")

load_scheduled()

# ==========================================================
#  ACCESS CONTROL - ENHANCED
# ==========================================================

def is_owner(uid):
    return uid in config.OWNER_IDS

def is_admin(uid):
    return is_owner(uid) or uid in [a['id'] for a in admins]

def get_user_limit(uid):
    """Returns account limit for user"""
    if is_owner(uid):
        return float('inf')
    
    admin_data = next((a for a in admins if a['id'] == uid), None)
    if admin_data:
        if admin_data.get('limit', 0) == 0:
            return float('inf')
        return int(admin_data.get('limit', 0))
    return 0

def get_admin_accounts(uid):
    """Get accounts accessible to this admin based on limit"""
    if is_owner(uid):
        return accounts.copy()
    
    limit = get_user_limit(uid)
    if limit == float('inf'):
        return accounts.copy()
    
    # Get admin's own accounts first
    user_accs = [a for a in accounts if a.get('owner') == uid]
    if len(user_accs) >= limit:
        return user_accs[:int(limit)]
    
    # Fill remaining with other accounts
    remaining = int(limit) - len(user_accs)
    other_accs = [a for a in accounts if a.get('owner') != uid]
    return user_accs + other_accs[:remaining]

def my_accounts(uid, limit=None):
    """Get accounts for user (fallback to old behavior)"""
    if limit is None:
        limit = get_user_limit(uid)
    
    user_accs = [a for a in accounts if a.get('owner') == uid]
    
    if limit == float('inf') or limit is None:
        return user_accs
    return user_accs[:int(limit)]

def get_total_accounts():
    return len(accounts)

def get_admin_usage_stats(admin_id):
    """Get usage statistics for an admin"""
    admin_campaigns = [c for c in campaigns if c.get('owner') == admin_id]
    total_votes = sum(c.get('ok', 0) for c in admin_campaigns)
    return {
        'total_campaigns': len(admin_campaigns),
        'total_votes': total_votes,
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
            config.API_ID,
            config.API_HASH,
            device_model="Desktop",
            system_version="Windows 10",
            app_version="4.16.8",
            connection_retries=3,
            retry_delay=2
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
        config.API_ID,
        config.API_HASH,
        device_model="Desktop",
        system_version="Windows 10"
    )
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        raise ValueError("Session expired / not authorized")
    return await save_session_account(c, owner)

# ==========================================================
#  CHANNEL INFO RESOLUTION - ENHANCED
# ==========================================================

class ChannelInfo:
    def __init__(self, entity, is_private=False, is_channel=True, is_group=False, 
                 username=None, invite_hash=None, title=None, access_hash=None,
                 can_join=True, join_required=False):
        self.entity = entity
        self.is_private = is_private
        self.is_channel = is_channel
        self.is_group = is_group
        self.username = username
        self.invite_hash = invite_hash
        self.title = title
        self.access_hash = access_hash
        self.can_join = can_join
        self.join_required = join_required

async def get_channel_info(client, ref):
    """Get detailed channel info including private/public status"""
    try:
        entity = await resolve_entity(client, ref)
        if not entity:
            return None
        
        is_channel = hasattr(entity, 'broadcast') and entity.broadcast
        is_group = hasattr(entity, 'group') and entity.group
        has_username = hasattr(entity, 'username') and entity.username
        
        channel_info = ChannelInfo(
            entity=entity,
            is_private=not has_username,
            is_channel=is_channel,
            is_group=is_group,
            username=getattr(entity, 'username', None),
            title=getattr(entity, 'title', None) or getattr(entity, 'first_name', 'Unknown'),
            access_hash=getattr(entity, 'access_hash', None)
        )
        
        # Check if we can join
        try:
            if has_username:
                # Public channel - can join directly
                channel_info.can_join = True
                channel_info.join_required = False
            else:
                # Private channel - need invite
                channel_info.can_join = False
                channel_info.join_required = True
        except Exception:
            pass
        
        return channel_info
    except Exception as e:
        print(f"[channel_info] Error: {e}")
        return None

async def resolve_entity(client, ref):
    kind, val = ref
    try:
        if kind == "username":
            # Try to resolve username
            try:
                return await client.get_entity(val)
            except Exception:
                # Try with @
                if not val.startswith('@'):
                    return await client.get_entity('@' + val)
                raise
        elif kind == "c":
            return await client.get_entity(PeerChannel(val))
        elif kind == "id":
            cid = abs(val) - 1000000000000 if val < 0 else val
            return await client.get_entity(PeerChannel(cid))
        elif kind == "invite":
            # Handle invite hash - try to get channel info
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

async def resolve_entity_cached(client, ref):
    key = str(ref)
    if key in entity_cache and entity_cache[key].get('expires', 0) > time.time():
        return entity_cache[key]['entity']
    entity = await resolve_entity(client, ref)
    if entity:
        entity_cache[key] = {'entity': entity, 'expires': time.time() + 3600}
    return entity

entity_cache = {}

# ==========================================================
#  PARSING FUNCTIONS - ENHANCED
# ==========================================================

POST_RE = re.compile(r"(?:https?://)?t\.me/(?:c/(\d+)/(\d+)|([A-Za-z0-9_]{4,})/(\d+))", re.I)
INVITE_RE = re.compile(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)", re.I)

def parse_post_url(url):
    """Parse post URL - returns (ref, msg_id)"""
    m = POST_RE.search(url.strip())
    if not m:
        return None
    if m.group(1):  # Private channel: t.me/c/1234567890/123
        return ("c", int(m.group(1))), int(m.group(2))
    return ("username", m.group(3)), int(m.group(4))  # Public channel

def parse_join_target(text):
    """Parse join target - supports both @username and invite links"""
    u = text.strip()
    
    # Check for invite link
    m = INVITE_RE.search(u)
    if m:
        return ("invite", m.group(1))
    
    # Check for username
    m = re.match(r"(?:https?://)?t\.me/@?([A-Za-z0-9_]{3,})/?$", u, re.I)
    if m:
        return ("username", m.group(1))
    
    # Check for @username
    if u.startswith("@") and len(u) > 3:
        return ("username", u[1:])
    
    # Check for channel ID
    if re.fullmatch(r"-?\d+", u):
        return ("id", int(u))
    
    return None

def parse_join_input(text):
    """Parse join input - handles both post and channel info"""
    # First check if it's a post URL
    post_parsed = parse_post_url(text)
    if post_parsed:
        return {"type": "post", "ref": post_parsed[0], "msg_id": post_parsed[1]}
    
    # Check if it's a channel join target
    join_target = parse_join_target(text)
    if join_target:
        return {"type": "channel", "target": join_target}
    
    return None

# ==========================================================
#  CAMPAIGN WORKERS - ENHANCED
# ==========================================================

RANDOM_EMOJIS = ["👍", "❤️", "🔥", "🎉", "👏", "😍", "💯", "⭐", "✨", "💪", "🤩", "🙌", "👑", "💎", "🚀"]

async def send_premium_reaction(c, ent, msg_id, emoji):
    """Send reaction with premium emoji support"""
    custom_id = PremiumEmojis.REACTION_EMOJIS.get(emoji)
    try:
        if custom_id:
            await c.send_reaction(ent, msg_id, reaction=ReactionEmoji(
                emoticon=emoji, custom_emoji_id=int(custom_id)))
        else:
            await c.send_reaction(ent, msg_id, reaction=ReactionEmoji(emoticon=emoji))
        return True
    except Exception as e:
        print(f"[reaction] Error: {e}")
        return False

async def do_react(c, ent, msg_id, emoji):
    """React to a message"""
    if emoji and emoji.lower() in ["random", "rand", "r", "🍀"]:
        emoji = random.choice(RANDOM_EMOJIS)
    return await send_premium_reaction(c, ent, msg_id, emoji)

async def do_vote(c, ent, msg_id, btn_index, btn_text):
    """Vote using inline button"""
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg or not msg.buttons:
            raise ValueError("No inline buttons on this post")
        
        # Find the button
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
            btn = msg.buttons[0][0]  # First button as fallback
        
        # Click the button
        await btn.click()
        return True
    except Exception as e:
        print(f"[vote] Error: {e}")
        return False

async def do_poll_vote(c, ent, msg_id, poll_options):
    """Vote in a poll"""
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg or not msg.poll:
            raise ValueError("Not a poll")
        
        answers = msg.poll.poll.answers
        opts = []
        for i in poll_options:
            if i < 0 or i >= len(answers):
                raise ValueError(f"Option {i} out of range (0-{len(answers)-1})")
            opts.append(answers[i].option)
        
        await c(SendVoteRequest(peer=ent, msg_id=msg_id, options=opts))
        return True
    except Exception as e:
        print(f"[poll_vote] Error: {e}")
        return False

async def do_view(c, ent, msg_id):
    """Mark message as viewed"""
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if msg:
            await c.send_read_acknowledge(ent, msg)
            return True
        return False
    except Exception as e:
        print(f"[view] Error: {e}")
        return False

async def do_join_channel(c, target, channel_info=None):
    """Join a channel - handles both public and private"""
    try:
        kind, val = target
        
        # If we have channel info, use it
        if channel_info and channel_info.is_private:
            # Private channel - need invite
            if channel_info.username:
                # Try public join first
                try:
                    await c(JoinChannelRequest(channel_info.username))
                    return True
                except Exception:
                    pass
            
            # Try using entity directly
            try:
                await c(JoinChannelRequest(channel_info.entity))
                return True
            except Exception:
                pass
        
        # Public channel or fallback
        if kind == "username":
            # Try to join by username
            try:
                await c(JoinChannelRequest(val))
                return True
            except UserAlreadyParticipantError:
                return True
            except Exception:
                # Try with @
                if not val.startswith('@'):
                    try:
                        await c(JoinChannelRequest('@' + val))
                        return True
                    except Exception:
                        pass
                raise
        
        elif kind == "id":
            try:
                entity = await resolve_entity(c, target)
                if entity:
                    await c(JoinChannelRequest(entity))
                    return True
            except Exception:
                raise
        
        elif kind == "invite":
            try:
                # Try to join with invite hash
                await c(ImportChatInviteRequest(val))
                return True
            except UserAlreadyParticipantError:
                return True
            except Exception:
                raise
        
        return False
    except UserAlreadyParticipantError:
        return True
    except Exception as e:
        print(f"[join] Error: {e}")
        return False

async def do_join_request(c, target, channel_info=None):
    """Send join request to private channel"""
    try:
        kind, val = target
        
        if channel_info and channel_info.is_private:
            # Private channel - try to join with request
            try:
                # First try to join directly
                result = await do_join_channel(c, target, channel_info)
                if result:
                    return True
            except Exception:
                pass
            
            # If direct join fails, try import invite
            if kind == "invite":
                try:
                    await c(ImportChatInviteRequest(val))
                    return True
                except Exception:
                    pass
        
        # Fallback to regular join
        return await do_join_channel(c, target, channel_info)
    except Exception as e:
        print(f"[join_request] Error: {e}")
        return False

async def do_leave_channel(c, target):
    """Leave a channel"""
    try:
        kind, val = target
        if kind == "invite":
            raise ValueError("Cannot leave via invite link")
        
        entity = await resolve_entity(c, target)
        if entity:
            await c(LeaveChannelRequest(entity))
            return True
        return False
    except Exception as e:
        print(f"[leave] Error: {e}")
        return False

async def do_dm(c, target, text):
    """Send DM to user"""
    try:
        kind, val = target
        if kind == "invite":
            raise ValueError("DM target must be @username or user id")
        
        if kind == "username":
            entity = await c.get_entity(val)
        else:
            entity = await c.get_entity(val)
        
        await c.send_message(entity, text)
        return True
    except Exception as e:
        print(f"[dm] Error: {e}")
        return False

# ==========================================================
#  CAMPAIGN EXECUTION - ENHANCED WITH CHANNEL INFO
# ==========================================================

async def get_channel_info_for_campaign(uid, post_ref, target=None):
    """Get channel info for campaign - tries multiple methods"""
    # Try to get info from post first
    first_acc = None
    accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
    if not accs:
        return None
    
    first_acc = await get_client(accs[0])
    if not first_acc:
        return None
    
    try:
        # Try to get channel info from post
        if post_ref:
            entity = await resolve_entity_cached(first_acc, post_ref)
            if entity:
                return await get_channel_info(first_acc, post_ref)
        
        # Try from target
        if target:
            entity = await resolve_entity_cached(first_acc, target)
            if entity:
                return await get_channel_info(first_acc, target)
    except Exception as e:
        print(f"[channel_info] Error: {e}")
    
    return None

async def run_campaign(uid, action, opts):
    """Enhanced campaign runner with channel info and count control"""
    campaign_id = f"{uid}_{int(time.time())}"
    
    # Check if campaign should be stopped
    if campaign_id in active_campaigns and active_campaigns[campaign_id].get('stopped'):
        return 0, ["Campaign stopped by user"]
    
    # Get accounts
    count = int(opts.get("count", 0))
    if count <= 0:
        # Get accounts based on admin limit
        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
    else:
        accs = (get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))[:count]
    
    if not accs:
        return 0, ["No accounts found or Limit reached."]
    
    # Randomize accounts
    random.shuffle(accs)
    
    # Get settings
    st = get_settings(uid)
    ok, fail = 0, []
    
    # Parse options
    post_ref = opts.get("post_ref")
    msg_id = opts.get("msg_id")
    target = opts.get("target")
    emoji = opts.get("emoji")
    bi, bt = opts.get("btn_index"), opts.get("btn_text")
    poll_options = opts.get("poll_options", [])
    
    # Get channel info
    channel_info = None
    if post_ref or target:
        channel_info = await get_channel_info_for_campaign(uid, post_ref, target)
    
    # Store campaign info
    campaign_info = {
        'id': campaign_id,
        'owner': uid,
        'action': action,
        'opts': opts,
        'started': time.time(),
        'total': len(accs),
        'processed': 0,
        'status': 'running'
    }
    active_campaigns[campaign_id] = campaign_info
    running_campaigns[campaign_id] = campaign_info
    
    try:
        for i, acc in enumerate(accs):
            # Check if campaign should stop
            if campaign_id in active_campaigns and active_campaigns[campaign_id].get('stopped'):
                fail.append(f"Campaign stopped at {i} accounts")
                break
            
            try:
                c = await get_client(acc)
                if c is None:
                    fail.append(f"{acc['phone']}: Session expired")
                    continue
                
                # Get entity for post if needed
                ent = None
                if post_ref:
                    ent = await resolve_entity_cached(c, post_ref)
                    if not ent and target:
                        # Try using target as fallback
                        ent = await resolve_entity_cached(c, target)
                
                if action in ("react", "react_vote", "react_vote_view"):
                    if action == "react_vote_view":
                        await do_view(c, ent, msg_id)
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                    
                    success = await do_react(c, ent, msg_id, emoji)
                    if not success:
                        fail.append(f"{acc['phone']}: Reaction failed")
                        continue
                    
                    if action != "react":
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        success = await do_vote(c, ent, msg_id, bi, bt)
                        if not success:
                            fail.append(f"{acc['phone']}: Vote failed")
                            continue
                
                elif action == "vote":
                    success = await do_vote(c, ent, msg_id, bi, bt)
                    if not success:
                        fail.append(f"{acc['phone']}: Vote failed")
                        continue
                
                elif action == "poll_vote":
                    if isinstance(poll_options, str):
                        poll_options = [int(x.strip()) for x in poll_options.split(',') if x.strip().isdigit()]
                    success = await do_poll_vote(c, ent, msg_id, poll_options)
                    if not success:
                        fail.append(f"{acc['phone']}: Poll vote failed")
                        continue
                
                elif action == "view":
                    success = await do_view(c, ent, msg_id)
                    if not success:
                        fail.append(f"{acc['phone']}: View failed")
                        continue
                
                elif action == "join":
                    if target:
                        success = await do_join_channel(c, target, channel_info)
                        if not success:
                            fail.append(f"{acc['phone']}: Join failed")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue
                
                elif action == "join_request":
                    if target:
                        success = await do_join_request(c, target, channel_info)
                        if not success:
                            fail.append(f"{acc['phone']}: Join request failed")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue
                
                elif action == "leave":
                    if target:
                        success = await do_leave_channel(c, target)
                        if not success:
                            fail.append(f"{acc['phone']}: Leave failed")
                            continue
                    else:
                        fail.append(f"{acc['phone']}: No target specified")
                        continue
                
                elif action == "dm":
                    if target:
                        success = await do_dm(c, target, opts.get("dm_text", ""))
                        if not success:
                            fail.append(f"{acc['phone']}: DM failed")
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
            
            # Delay between accounts
            await asyncio.sleep(random.uniform(st["delay_min"], st["delay_max"]))
    
    finally:
        # Update campaign status
        campaign_info['status'] = 'completed'
        campaign_info['ended'] = time.time()
        campaign_info['ok'] = ok
        campaign_info['failed'] = len(fail)
        
        # Save to history
        campaign_history.append({
            "owner": uid,
            "action": action,
            "ok": ok,
            "fail": len(fail),
            "time": time.strftime("%d-%m %H:%M"),
            "total": len(accs),
            "duration": campaign_info['ended'] - campaign_info['started'],
            "campaign_id": campaign_id
        })
        save_campaign_history()
        
        # Remove from active
        active_campaigns.pop(campaign_id, None)
        running_campaigns.pop(campaign_id, None)
    
    return ok, fail

# ==========================================================
#  CAMPAIGN CONTROL FUNCTIONS
# ==========================================================

def stop_campaign(campaign_id):
    """Stop a running campaign"""
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['stopped'] = True
        return True
    return False

def get_running_campaigns():
    """Get list of running campaigns"""
    return list(running_campaigns.values())

async def scheduler_loop(bot):
    """Scheduler loop for scheduled campaigns"""
    while True:
        now = time.time()
        for s in [x for x in scheduled if x["run_at"] <= now]:
            scheduled.remove(s)
            save_scheduled()
            try:
                ok, fail = await run_campaign(s["owner"], s["action"], s["opts"])
                txt = (f"⏰ **Scheduled Campaign Completed**\n"
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
    config.API_ID,
    config.API_HASH
).start(bot_token=config.BOT_TOKEN)

# Actions list
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

# Main menu buttons
MAIN_MENU = [
    [Button.inline(f"{PremiumEmojis.ID} My Account", b"myacc"),
     Button.inline(f"{PremiumEmojis.CONNECT} Add Account", b"add")],
    [Button.inline(f"{PremiumEmojis.CREATE} New Campaign", b"camp"),
     Button.inline(f"{PremiumEmojis.CHART} My Campaigns", b"mycamp")],
    [Button.inline(f"{PremiumEmojis.CLOCK} Running", b"running"),
     Button.inline(f"{PremiumEmojis.STATS} My Status", b"mystat")],
    [Button.inline(f"{PremiumEmojis.SETTINGS} Settings", b"set"),
     Button.inline(f"{PremiumEmojis.ADMIN} Owner Panel", b"owner_panel")],
    [Button.inline(f"{PremiumEmojis.CANCEL} Leave Channel", b"leave_menu"),
     Button.inline(f"{PremiumEmojis.SEARCH} Help", b"help")],
    [Button.inline(f"{PremiumEmojis.CLEAR} Remove Account", b"remove_acc")],
]

def menu_text(uid):
    """Generate menu text with account info"""
    my = len(my_accounts(uid))
    limit = get_user_limit(uid)
    limit_text = "Unlimited" if is_owner(uid) else (f"{limit}" if is_admin(uid) else "0")
    
    # Get admin accessible accounts if admin
    if is_admin(uid) and not is_owner(uid):
        accessible = len(get_admin_accounts(uid))
        my = accessible
    
    text = (f"{PremiumEmojis.CROWN} **╔═══ VOTEFLOW BOT ═══╗**\n\n"
            f"{PremiumEmojis.STATS} **Your Stats:**\n"
            f"┌──────────────────────┐\n"
            f"│ Your Accounts: **{my}**\n"
            f"│ Your Limit: **{limit_text}**\n")
    
    if is_admin(uid):
        total = get_total_accounts()
        text += f"│ Total Bot Accounts: **{total}**\n"
    
    text += (f"└──────────────────────┘\n\n"
             f"{PremiumEmojis.LOCK} **Access:** **{'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}**\n")
    
    # Global stats for owner
    if is_owner(uid):
        running = len(get_running_campaigns())
        text += (f"{PremiumEmojis.CHART} **Global Stats:**\n"
                 f"Total Accounts: **{get_total_accounts()}**\n"
                 f"Running Campaigns: **{running}**\n"
                 f"Total Users: **{len(set(a.get('owner') for a in accounts))}**\n")
    
    return text

def no_access():
    return f"{PremiumEmojis.ALERT} **Access Denied!**\nOnly Owner/Admins can run campaigns."

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
    total_accs = len(my_accounts(uid))
    if is_admin(uid):
        total_accs = len(get_admin_accounts(uid))
    
    await e.reply(f"{PremiumEmojis.ID} **My Profile**\n"
                  f"ID: `{uid}`\n"
                  f"Access: {'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}\n"
                  f"Accounts: {total_accs}\n"
                  f"Limit: {get_user_limit(uid)}", parse_mode="md")

@bot.on(events.NewMessage(pattern="^/check$"))
async def cmd_check(e):
    uid = e.sender_id
    
    if is_admin(uid):
        # Get all accessible accounts
        accs = get_admin_accounts(uid)
        total = len(accs)
        active = 0
        expired = []
        
        for acc in accs[:20]:  # Limit to 20 for speed
            c = await get_client(acc)
            if c is None:
                expired.append(acc)
            else:
                try:
                    await c.get_me()
                    active += 1
                except Exception:
                    expired.append(acc)
        
        lines = [f"📋 **Account Report**",
                f"👤 User ID: `{uid}`",
                f"Access: {'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}",
                f"➖➖➖➖➖➖➖➖➖➖➖",
                f"👥 **Total Accessible:** {total}",
                f"🟢 **Active:** {active}",
                f"🔴 **Expired/Failed:** {len(expired)}"]
        
        if expired:
            lines.append("\n❌ **Expired Account Details:**")
            for acc in expired[:10]:
                lines.append(f"🔴 `{acc['phone']}` — Session Expired")
        
        await e.reply("\n".join(lines), parse_mode="md")
    else:
        # Regular user check
        total, active, expired, user_accs = await check_status(uid)
        await e.reply(f"📋 **Account Report**\n"
                      f"Total: {total}\nActive: {active}\nExpired: {len(expired)}", parse_mode="md")

async def check_status(uid):
    """Check status of user accounts"""
    user_accs = [a for a in accounts if a.get("owner") == uid]
    total = len(user_accs)
    active, expired = 0, []
    
    for a in user_accs[:20]:  # Limit for speed
        c = await get_client(a)
        if c is None:
            expired.append(a)
        else:
            try:
                await c.get_me()
                active += 1
            except Exception:
                expired.append(a)
    
    return total, active, expired, user_accs

@bot.on(events.NewMessage(pattern="^/addadmin(@\w+)?(\s+.*)?$"))
async def cmd_addadmin(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Owner Only!", parse_mode="md")
    
    target_id = None
    limit = 0
    
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
    
    # Update or add admin
    admin_exists = next((a for a in admins if a['id'] == target_id), None)
    if admin_exists:
        admin_exists['limit'] = limit
        save_admins()
        limit_text = "Unlimited" if limit == 0 else str(limit)
        return await e.reply(f"✅ Admin Limit Updated for `{target_id}`: **{limit_text}** accounts", parse_mode="md")
    
    admins.append({"id": target_id, "limit": limit})
    save_admins()
    
    limit_text = "Unlimited" if limit == 0 else str(limit)
    await e.reply(f"✅ **`{target_id}` is now Admin!** (Limit: **{limit_text}** accounts)", parse_mode="md")
    try:
        await bot.send_message(target_id, f"🎉 You got **Admin access**! Limit: **{limit_text}** accounts")
    except Exception:
        pass

@bot.on(events.NewMessage(pattern="^/rmadmin(\s+.*)?$"))
async def cmd_rmadmin(e):
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
            lines.append(f"· `{a['id']}` — {u.first_name} (Limit: {limit_text})")
            lines.append(f"  Campaigns: {stats['total_campaigns']}, Votes: {stats['total_votes']}")
        except Exception:
            limit_text = "Unlimited" if a.get('limit', 0) == 0 else str(a.get('limit', 0))
            lines.append(f"· `{a['id']}` — (Unknown) (Limit: {limit_text})")
    await e.reply("\n".join(lines), parse_mode="md")

@bot.on(events.NewMessage(pattern="^/stop(\s+.*)?$"))
async def cmd_stop(e):
    """Stop a running campaign"""
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
        # Show running campaigns
        running = get_running_campaigns()
        if not running:
            return await e.reply("No running campaigns.", parse_mode="md")
        
        lines = ["⏹️ **Running Campaigns:**"]
        for c in running:
            lines.append(f"· `{c['id']}` — {c['action']} ({c['processed']}/{c['total']})")
        lines.append("\nUse `/stop <campaign_id>` to stop")
        await e.reply("\n".join(lines), parse_mode="md")

# ==========================================================
#  CALLBACK ROUTER - ENHANCED
# ==========================================================

@bot.on(events.CallbackQuery())
async def cb(e):
    uid = e.sender_id
    data = e.data.decode()
    s = state(uid)
    
    if data == "menu":
        reset(uid)
        return await e.edit(menu_text(uid), buttons=MAIN_MENU, parse_mode="md")
    
    # ── Running Campaigns ──
    if data == "running":
        running = get_running_campaigns()
        if not running:
            return await e.edit("No running campaigns.", buttons=[[Button.inline("« Back", b"menu")]])
        
        lines = ["⏱️ **Running Campaigns:**"]
        for c in running:
            progress = f"{c['processed']}/{c['total']}" if c['total'] > 0 else "Processing"
            lines.append(f"· `{c['id'][:8]}` — {c['action']} ({progress})")
            lines.append(f"  Started: {datetime.fromtimestamp(c['started']).strftime('%H:%M')}")
        
        await e.edit("\n".join(lines), buttons=[[Button.inline("« Back", b"menu")]])
    
    # ── Owner Panel ──
    if data == "owner_panel":
        if not is_owner(uid):
            return await e.answer("⛔ Owner Only!", alert=True)
        
        total_users = len(set(a.get("owner") for a in accounts))
        running = len(get_running_campaigns())
        
        lines = [f"👑 **Owner Panel**\n"
                f"Global Accounts: {len(accounts)}\n"
                f"Users: {total_users}\n"
                f"Admins: {len(admins)}\n"
                f"Running Campaigns: {running}\n"
                f"Scheduled: {len(scheduled)}"]
        
        if admins:
            lines.append("\n**Admins:**")
            for a in admins[:10]:
                try:
                    u = await bot.get_entity(a['id'])
                    limit_text = "Unlimited" if a.get('limit', 0) == 0 else str(a.get('limit', 0))
                    lines.append(f"· `{a['id']}` — {u.first_name} (Limit: {limit_text})")
                except Exception:
                    limit_text = "Unlimited" if a.get('limit', 0) == 0 else str(a.get('limit', 0))
                    lines.append(f"· `{a['id']}` — (Unknown) (Limit: {limit_text})")
        else:
            lines.append("· No admins")
        
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])
    
    # ── My Account ──
    if data == "myacc" or data == "profile":
        if is_admin(uid):
            # Show admin accessible accounts
            accs = get_admin_accounts(uid)
            total = len(accs)
            active = 0
            expired = []
            
            for acc in accs[:15]:
                c = await get_client(acc)
                if c is None:
                    expired.append(acc)
                else:
                    try:
                        await c.get_me()
                        active += 1
                    except Exception:
                        expired.append(acc)
            
            lines = [f"🧑‍💼 **My Profile**\nID: `{uid}`\nAccess: **{'👑 Owner' if is_owner(uid) else '✅ Admin'}**"]
            lines.append(f"📊 Accessible Accounts: {total} | Active: {active} | Expired: {len(expired)}")
            
            if accs:
                lines.append("\n**Accounts (Sample):**")
                for a in accs[:10]:
                    if a["phone"] in clients:
                        lines.append(f"🟢 `{a['phone']}` — {a.get('name','?')}")
                    else:
                        lines.append(f"🔴 `{a['phone']}` — {a.get('name','?')} (Expired)")
            
            if expired:
                lines.append("\n❌ **Expired Accounts:**")
                for acc in expired[:5]:
                    lines.append(f"🔴 `{acc['phone']}`")
        else:
            # Regular user
            total, active, expired, user_accs = await check_status(uid)
            lines = [f"🧑‍💼 **My Profile**\nID: `{uid}`\nAccess: **👤 User**"]
            lines.append(f"📊 Accounts: {total} | Active: {active} | Expired: {len(expired)}")
            
            if user_accs:
                lines.append("\n**Your Accounts:**")
                for a in user_accs:
                    if a["phone"] in clients:
                        lines.append(f"🟢 `{a['phone']}` — {a.get('name','?')}")
                    else:
                        lines.append(f"🔴 `{a['phone']}` — {a.get('name','?')} (Expired)")
        
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])
    
    # ── My Status ──
    if data == "mystat":
        myc = [c for c in campaigns if c["owner"] == uid]
        lines = [f"📊 **My Status**"]
        if is_admin(uid):
            accs = get_admin_accounts(uid)
            lines.append(f"Accessible Accounts: {len(accs)}")
        else:
            total, active, expired, _ = await check_status(uid)
            lines.append(f"Your Accounts: {total} | Active: {active}")
        
        lines.append(f"Campaigns Run: {len(myc)}")
        lines.append(f"Scheduled: {len([x for x in scheduled if x['owner']==uid])}")
        
        if myc:
            lines.append("\n**Last 5 Campaigns:**")
            for c in myc[-5:]:
                lines.append(f"· `{c['time']}` {c['action']} ✅{c['ok']} ❌{c['fail']}")
        
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])
    
    # ── My Campaigns ──
    if data == "mycamp":
        myc = [c for c in campaigns if c["owner"] == uid]
        if not myc:
            return await e.edit("📋 No campaigns.", buttons=[[Button.inline("« Back", b"menu")]])
        
        lines = [f"📋 **My Campaigns ({len(myc)})**"]
        for c in myc[-15:]:
            lines.append(f"· `{c['time']}` {c['action']} ✅{c['ok']} ❌{c['fail']}")
        
        # Add history
        history = [h for h in campaign_history if h["owner"] == uid]
        if history:
            lines.append("\n**History Stats:**")
            total_votes = sum(h.get('ok', 0) for h in history)
            lines.append(f"Total Actions: {total_votes}")
        
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])
    
    # ── Help ──
    if data == "help":
        return await e.edit(
            "❓ **Help - VoteFlow Bot**\n\n"
            "**📋 How to use:**\n"
            "1️⃣ **Add Accounts** — Phone+OTP / Session String / Bulk\n"
            "2️⃣ **Create Campaign** — Select action and configure\n"
            "3️⃣ **Run Campaign** — Choose accounts and execute\n\n"
            "**📌 Campaign Actions:**\n"
            "• **React** — React with emoji to post\n"
            "• **Vote** — Click inline button (vote)\n"
            "• **Poll Vote** — Vote in poll\n"
            "• **Join** — Join channel/group\n"
            "• **Join Request** — Send join request\n"
            "• **Leave** — Leave channel/group\n"
            "• **DM** — Send direct message\n\n"
            "**📊 Private/Public Channels:**\n"
            "• **Public:** Just the post URL works\n"
            "• **Private:** Need channel link + post URL\n"
            "• **Join Request:** Use join request action\n\n"
            "**🔧 Commands:**\n"
            "/start — Menu\n"
            "/me — Stats\n"
            "/check — Account report\n"
            "/addadmin — Add admin\n"
            "/rmadmin — Remove admin\n"
            "/adminlist — List admins\n"
            "/stop — Stop campaign\n\n"
            "💡 **Tips:**\n"
            "• For private channels, provide both post URL and channel invite link\n"
            "• Count controls how many accounts to use\n"
            "• Use 0 for max available accounts",
            parse_mode="md",
            buttons=[[Button.inline("« Back", b"menu")]]
        )
    
    # ── Add Account ──
    if data == "add":
        s.clear()
        return await e.edit(f"{PremiumEmojis.CONNECT} **Add Account**",
                            buttons=[[Button.inline("📱 Phone + OTP", b"add_phone")],
                                     [Button.inline("🔑 Session String", b"add_string")],
                                     [Button.inline("📋 Bulk Sessions", b"bulk")],
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
        return await e.edit("📋 **Bulk Sessions**\nPaste strings (1 per line) or upload .txt",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")
    
    # ── Remove Account ──
    if data == "remove_acc":
        s.clear()
        s["step"] = "remove_input"
        return await e.edit(f"{PremiumEmojis.CLEAR} **Remove Account**\nSend phone number:\n`+919876543210`\n\n⚠️ Permanent!",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")
    
    # ── Settings ──
    if data == "set":
        st = get_settings(uid)
        s["step"] = "set"
        return await e.edit(f"⚙️ **Settings**\nDelay: `{st['delay_min']}`–`{st['delay_max']}` sec\n\nSet new: `min-max` (eg `1-3`)",
                            buttons=[[Button.inline("« Back", b"menu")]], parse_mode="md")
    
    # ── Leave Menu ──
    if data == "leave_menu":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s.clear()
        s["step"] = "camp_target"
        s["camp_action"] = "leave"
        return await e.edit("🚪 **Leave Channel**",
                            buttons=[[Button.inline("📂 Show My Chats", b"list_chats")],
                                     [Button.inline("✍️ Manual", b"leave_manual")],
                                     [Button.inline("« Cancel", b"menu")]])
    
    if data == "leave_manual":
        s["step"] = "camp_target"
        return await e.edit("🚪 Send @username or chat id:",
                            buttons=[[Button.inline("« Cancel", b"menu")]])
    
    if data == "list_chats":
        accs = get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid)
        if not accs:
            return await e.edit("❌ Add account first.", buttons=[[Button.inline("« Back", b"menu")]])
        
        c = await get_client(accs[0])
        if not c:
            return await e.edit("❌ Account dead.", buttons=[[Button.inline("« Back", b"menu")]])
        
        dialogs = await c.get_dialogs(limit=25)
        btns = []
        for d in dialogs:
            if d.is_group or d.is_channel:
                btns.append([Button.inline(f"🚪 {d.name[:30]}", f"doleave:{d.id}".encode())])
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
    
    # ── Campaign ──
    if data == "camp":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s.clear()
        s["step"] = "camp_action"
        btns = []
        for key, label in ACTIONS:
            btns.append([Button.inline(label, f"act:{key}".encode())])
        btns.append([Button.inline("« Back", b"menu")])
        return await e.edit("🚀 **New Campaign**\nSelect action:", buttons=btns, parse_mode="md")
    
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
                "join": f"{PremiumEmojis.JOIN} **Join Channel**\n\nSend channel link or username:\n`@channel`\n`https://t.me/channel`\n`https://t.me/+invite_hash`\n\n💡 For private channels, use invite link",
                "join_request": f"{PremiumEmojis.REQUEST} **Join Request**\n\nSend channel invite link:\n`https://t.me/+invite_hash`\n\n💡 Use this for private channels requiring approval",
                "leave": f"{PremiumEmojis.CANCEL} **Leave**\nSend channel link or username",
                "dm": f"{PremiumEmojis.SPEAKER} **DM**\nSend username or user id",
            }
            return await e.edit(hints[key], buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")
        
        s["step"] = "camp_post"
        return await e.edit(f"{PremiumEmojis.CHANNEL} **Post URL**\n\nSend the post URL:\n`https://t.me/channel/123`\n`https://t.me/c/1234567890/123`\n\n💡 For private channels, you'll need to provide channel link next",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")
    
    # ── Run / Schedule ──
    if data == "run_now":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s = state(uid)
        await e.edit("⏳ Running campaign...")
        ok, fail = await run_campaign(uid, s["camp_action"], s["camp_opts"])
        lines = [f"✅ **Completed** — {ok} success, {len(fail)} failed"]
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
#  TEXT STEP HANDLER - ENHANCED
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
    
    # Phone + OTP
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
        return await e.reply("🔢 Code sent! Send OTP (eg `1 2 3 4 5 6`)")
    
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
    
    # Session string
    if step == "add_string_input":
        try:
            acc = await validate_session_string(text, uid)
        except Exception as ex:
            return await e.reply(f"❌ {ex}\nSend valid string:")
        reset(uid)
        return await e.reply(f"✅ Added `{acc['phone']}` — {acc['name']}",
                             buttons=MAIN_MENU, parse_mode="md")
    
    # Bulk
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
    
    # Remove Account
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
    
    # Settings
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
    
    # ── Campaign steps ──
    if step in ("camp_post", "camp_count", "camp_emoji", "camp_btn", "camp_target",
                "camp_dm_text", "sched_time", "camp_poll_options", "camp_channel_target"):
        if not is_admin(uid):
            reset(uid)
            return await e.reply(no_access())
    
    if step == "camp_post":
        # Parse post URL
        parsed = parse_post_url(text)
        if not parsed:
            return await e.reply("❌ Invalid post URL.\n\nFormat:\n`https://t.me/channel/123`\n`https://t.me/c/1234567890/123`", parse_mode="md")
        
        s["camp_opts"] = {"post_ref": parsed[0], "msg_id": parsed[1]}
        s["step"] = "camp_count"
        total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        return await e.reply(f"🔢 **How many accounts to use?**\n\nAvailable: **{total_accs}**\n`0` = All available\n\n💡 This controls how many accounts will be used", parse_mode="md")
    
    if step == "camp_count":
        if not text.isdigit():
            return await e.reply("❌ Send a number (e.g. `50`). `0` means all available.", parse_mode="md")
        s["camp_opts"]["count"] = int(text)
        
        # Check if we need channel info for private posts
        action = s["camp_action"]
        
        # For join/leave actions, we already handled target
        if action in ("join", "join_request", "leave"):
            # Check if we have target
            if "target" not in s["camp_opts"]:
                s["step"] = "camp_target"
                return await e.reply(f"📌 **Send channel target:**\n\nUsername: `@channel`\nInvite: `https://t.me/+invite_hash`\nID: `-1001234567890`", parse_mode="md")
            return await ask_run(e, uid)
        
        # For DM action
        if action == "dm":
            if "target" not in s["camp_opts"]:
                s["step"] = "camp_target"
                return await e.reply("📩 **Send username or user ID:**\n\n`@username` or `123456789`", parse_mode="md")
            if "dm_text" not in s["camp_opts"]:
                s["step"] = "camp_dm_text"
                return await e.reply("✉️ **Send DM message:**\n\nType the message you want to send", parse_mode="md")
            return await ask_run(e, uid)
        
        # For reactions and votes
        if action in ("react", "react_vote", "react_vote_view"):
            s["step"] = "camp_emoji"
            return await e.reply("😀 **Send emoji:**\n\nExample: `👍` `❤️` `🔥` or `🍀` for random\n\n💡 Premium emojis also supported", parse_mode="md")
        
        if action in ("vote", "poll_vote"):
            if action == "poll_vote":
                s["step"] = "camp_poll_options"
                return await e.reply("📊 **Poll Options:**\n\nSend poll option numbers (comma separated):\n`0,1,2`\n(0 = first option, 1 = second…)", parse_mode="md")
            else:
                s["step"] = "camp_btn"
                return await e.reply("🗳️ **Button Selection:**\n\nSend button number or button text:\n`1` (first button)\n`Vote` (button text)\n\n💡 Find the button number from the post", parse_mode="md")
        
        # For other actions
        return await ask_run(e, uid)
    
    if step == "camp_emoji":
        if not text.strip():
            return await e.reply("❌ Send an emoji!")
        s["camp_opts"]["emoji"] = text.strip()
        
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            s["step"] = "camp_btn"
            return await e.reply("🗳️ **Vote Button:**\n\nSend button number or text:\n`1` or `Vote Now`", parse_mode="md")
        
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
        # Parse target (for join, leave, dm)
        parsed = parse_join_target(text)
        if not parsed:
            return await e.reply("❌ Invalid target.\n\nFormat:\n`@channel`\n`https://t.me/+invite_hash`\n`https://t.me/channel`\n`-1001234567890`", parse_mode="md")
        
        s["camp_opts"]["target"] = parsed
        
        # For DM, ask for message
        if s["camp_action"] == "dm":
            s["step"] = "camp_dm_text"
            return await e.reply("✉️ **Send DM message:**\n\nType the message you want to send", parse_mode="md")
        
        # For join actions, check if we need to ask for count
        if s["camp_action"] in ("join", "join_request", "leave"):
            s["step"] = "camp_count"
            total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
            return await e.reply(f"🔢 **How many accounts to use?**\n\nAvailable: **{total_accs}**\n`0` = All available\n\n💡 This controls how many accounts will be used", parse_mode="md")
        
        return await ask_run(e, uid)
    
    if step == "camp_dm_text":
        s["camp_opts"]["dm_text"] = text
        s["step"] = "camp_count"
        total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        return await e.reply(f"🔢 **How many accounts to use?**\n\nAvailable: **{total_accs}**\n`0` = All available", parse_mode="md")
    
    if step == "sched_time":
        m = re.fullmatch(r"(\d+)([mhd])", text.lower())
        if not m:
            return await e.reply("❌ Format: `30m`, `2h`, `1d`", parse_mode="md")
        mult = {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
        s["sched_delay"] = int(m.group(1)) * mult
        label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
        return await e.reply(f"📅 **{label}** in **{text}**. Confirm?",
                             buttons=[[Button.inline("✅ Confirm", b"do_schedule")],
                                      [Button.inline("❌ Cancel", b"menu")]])

async def ask_run(e, uid):
    """Ask user to run or schedule the campaign"""
    s = state(uid)
    s["step"] = None
    label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
    opts = s.get("camp_opts", {})
    
    summary = f"🚀 **Campaign Ready**\n\nAction: **{label}**\n"
    if "post_ref" in opts:
        summary += f"Post ID: `{opts['msg_id']}`\n"
    if "count" in opts:
        count = opts['count']
        total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        if count == 0:
            summary += f"Accounts: **All ({total_accs})**\n"
        else:
            summary += f"Accounts: **{min(count, total_accs)}**\n"
    if "emoji" in opts:
        emoji_display = "🍀 Random" if opts['emoji'].lower() in ["random", "rand", "r", "🍀"] else opts['emoji']
        summary += f"Emoji: {emoji_display}\n"
    if opts.get("btn_index") or opts.get("btn_text"):
        summary += f"Button: `{opts.get('btn_index') or opts.get('btn_text')}`\n"
    if "target" in opts:
        summary += f"Target: `{opts['target'][1]}`\n"
    if "dm_text" in opts:
        summary += f"Message: {opts['dm_text'][:60]}\n"
    if "poll_options" in opts:
        summary += f"Poll Options: {opts['poll_options']}\n"
    
    summary += f"\n📊 Available Accounts: **{len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))}**"
    
    await e.reply(summary, parse_mode="md")
    await e.reply("▶️ **Run now or schedule?**",
                  buttons=[[Button.inline("▶️ Run Now", b"run_now"),
                            Button.inline("📅 Schedule", b"schedule_btn")],
                           [Button.inline("« Cancel", b"menu")]])

@bot.on(events.CallbackQuery(pattern=b"^schedule_btn$"))
async def sched_btn(e):
    if not is_admin(e.sender_id):
        return await e.answer(no_access(), alert=True)
    s = state(e.sender_id)
    s["step"] = "sched_time"
    await e.edit("📅 **Schedule Time**\n\nSend delay: `30m` / `2h` / `1d`",
                 buttons=[[Button.inline("« Cancel", b"menu")]])

# .txt file upload handler
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
    
    # Preload clients
    print("[VoteFlow] Preloading accounts...")
    for acc in accounts[:10]:  # Load first 10 only
        try:
            await get_client(acc)
        except Exception as ex:
            print(f"[load] {acc['phone']}: {ex}")
    
    # Start scheduler
    asyncio.create_task(scheduler_loop(bot))
    
    print(f"[VoteFlow] Running. Accounts: {len(accounts)}, Admins: {len(admins)+1}, Scheduled: {len(scheduled)}")
    print(f"[VoteFlow] Admin Limits active: {sum(1 for a in admins if a.get('limit', 0) > 0)} admins have limits")
    
    await bot.run_until_disconnected()

if __name__ == "__main__":
    bot.loop.run_until_complete(main())
