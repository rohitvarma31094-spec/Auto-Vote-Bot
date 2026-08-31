import asyncio
import json
import os
import random
import re
import threading
import time

from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, FloodWaitError, UserAlreadyParticipantError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    ImportChatInviteRequest, SendVoteRequest, GetBotCallbackAnswerRequest
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import PeerChannel, ReactionEmoji

import config

os.makedirs(config.SESSIONS_DIR, exist_ok=True)
LOCK = threading.Lock()

# ==========================================================
#  PREMIUM EMOJIS (Unicode - works on all devices)
# ==========================================================

class PremiumEmojis:
    VOTE = "🗳️"          ; JOIN = "➕"          ; CANCEL = "❌"
    MAIN_MENU = "🏠"     ; BACK = "🔙"          ; CREATE = "🚀"
    CONNECT = "🔗"       ; MANAGE = "🛠️"        ; ADD_VOTES = "➕"
    REMOVE_VOTES = "➖"  ; LEADERBOARD = "🏆"   ; END_GIVEAWAY = "🏁"
    ADMIN = "👑"         ; BROADCAST = "📢"     ; STATS = "📊"
    SETTINGS = "⚙️"      ; USERS = "👥"         ; BACKUP = "💾"
    CLEAR = "🗑️"         ; CHANNEL = "📡"       ; NOTIFICATION = "🔔"
    CONFIRM = "✅"       ; REFRESH = "🔄"       ; WELCOME = "👋"
    FIRE = "🔥"          ; ARROW = "➡️"         ; CHART = "📈"
    HEART = "❤️"         ; ROCKET = "🚀"        ; CROWN = "👑"
    ERROR = "⚠️"         ; ENDED = "🏁"         ; STAR = "⭐"
    ID = "🆔"            ; GIFT = "🎁"          ; WINE = "🍷"
    SMILE = "🙂"         ; LOVE = "😍"          ; LIGHTNING = "⚡"
    POINTER = "👉"       ; ALERT = "🚨"         ; CLOWN = "🤡"
    SEARCH = "🔍"        ; SPEAKER = "🔊"       ; LINK = "🔗"
    CONFETTI = "🎉"      ; LOCATION = "📍"      ; RIGHT = "✔️"
    DIAMOND = "💎"       ; CALENDAR = "📅"      ; WINNER = "🏅"
    MONEY_BAG = "💰"     ; CELEBRATE = "🎊"     ; INBOX = "📥"
    LOCK = "🔒"          ; SHIELD = "🛡️"        ; JOIN_CHANNEL = "📨"
    JOINED = "✔️"        ; EXPORT = "📤"        ; IMPORT = "📥"

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
#  STORAGE - PERSISTENT DATA
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

accounts  = jload(config.ACCOUNTS_FILE, [])
admins    = jload(config.ADMINS_FILE, [])
settings  = jload(config.SETTINGS_FILE, {})
campaigns = jload(config.CAMPAIGNS_FILE, [])

def save_accounts():  jsave(config.ACCOUNTS_FILE, accounts)
def save_admins():    jsave(config.ADMINS_FILE, admins)
def save_settings():  jsave(config.SETTINGS_FILE, settings)
def save_campaigns(): jsave(config.CAMPAIGNS_FILE, campaigns)

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

# ==========================================================
#  ACCESS CONTROL (WITH ADMIN LIMIT)
# ==========================================================

def is_owner(uid):
    return uid in config.OWNER_IDS

def is_admin(uid):
    return is_owner(uid) or uid in admins

def get_user_limit(uid):
    # Owner = Unlimited, Admin = Limit from config
    if is_owner(uid):
        return float('inf')
    if is_admin(uid):
        return getattr(config, 'ADMIN_ACCOUNT_LIMIT', 100)
    return 0

def my_accounts(uid, limit=None):
    user_accs = [a for a in accounts if a.get("owner") == uid]
    if limit is None:
        limit = get_user_limit(uid)
    return user_accs[:limit]

def get_total_accounts():
    return len(accounts)

# ==========================================================
#  USER STATE & CLIENTS
# ==========================================================

user_state = {}
clients = {}

def state(uid):
    return user_state.setdefault(uid, {})

def reset(uid):
    user_state.pop(uid, None)

def get_settings(uid):
    return settings.setdefault(str(uid), {"delay_min": 1.0, "delay_max": 2.5})

async def get_client(acc):
    phone = acc["phone"]
    if phone in clients and clients[phone].is_connected():
        return clients[phone]
    c = TelegramClient(StringSession(acc["string"]), config.API_ID, config.API_HASH,
                       device_model="Desktop", system_version="Windows 10",
                       app_version="4.16.8")
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        return None
    clients[phone] = c
    return c

async def save_session_account(c, owner):
    me = await c.get_me()
    phone = me.phone or "unknown"
    acc = {"phone": phone, "name": (me.first_name or "").strip(),
           "string": c.session.save(), "id": me.id, "owner": owner}
    clients[phone] = c
    for i, a in enumerate(accounts):
        if a["phone"] == phone:
            accounts[i] = acc
            save_accounts()
            return acc
    accounts.append(acc)
    save_accounts()
    return acc

async def validate_session_string(s, owner):
    c = TelegramClient(StringSession(s.strip()), config.API_ID, config.API_HASH,
                       device_model="Desktop", system_version="Windows 10")
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        raise ValueError("Session expired / not authorized")
    return await save_session_account(c, owner)

async def check_status(uid):
    user_accs = my_accounts(uid)
    total = len(user_accs)
    active, expired = 0, []
    
    for a in user_accs:
        c = await get_client(a)
        if c is None:
            expired.append(f"{a['phone']} ({a.get('name','?')}) - Session Expired")
        else:
            try:
                await c.get_me()
                active += 1
            except Exception as e:
                expired.append(f"{a['phone']} ({a.get('name','?')}) - {str(e)[:20]}")
    return total, active, expired

# ==========================================================
#  PARSING & ENTITY RESOLUTION
# ==========================================================

POST_RE = re.compile(r"(?:https?://)?t\.me/(?:c/(\d+)/(\d+)|([A-Za-z0-9_]{4,})/(\d+))", re.I)

def parse_post_url(url):
    m = POST_RE.search(url.strip())
    if not m:
        return None
    if m.group(1):
        return ("c", int(m.group(1))), int(m.group(2))
    return ("username", m.group(3)), int(m.group(4))

def parse_target(text):
    u = text.strip()
    m = re.search(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)", u, re.I)
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

async def resolve_entity(client, ref):
    kind, val = ref
    if kind == "username":
        return await client.get_entity(val)
    if kind == "c":
        return await client.get_entity(PeerChannel(val))
    if kind == "id":
        cid = abs(val) - 1000000000000 if val < 0 else val
        return await client.get_entity(PeerChannel(cid))
    return None

entity_cache = {}

async def resolve_entity_cached(client, ref):
    key = str(ref)
    if key in entity_cache and entity_cache[key].get('expires', 0) > time.time():
        return entity_cache[key]['entity']
    entity = await resolve_entity(client, ref)
    entity_cache[key] = {'entity': entity, 'expires': time.time() + 3600}
    return entity

# ==========================================================
#  CAMPAIGN WORKERS (WITH COUNT LOGIC)
# ==========================================================

RANDOM_EMOJIS = ["👍", "❤️", "🔥", "🎉", "👏", "😍", "💯", "⭐", "✨", "💪", "🤩", "🙌", "👑", "💎", "🚀"]

async def send_premium_reaction(c, ent, msg_id, emoji):
    custom_id = PremiumEmojis.REACTION_EMOJIS.get(emoji)
    if custom_id:
        try:
            await c.send_reaction(ent, msg_id, reaction=ReactionEmoji(
                emoticon=emoji, custom_emoji_id=int(custom_id)))
            return True
        except Exception:
            pass
    try:
        await c.send_reaction(ent, msg_id, reaction=ReactionEmoji(emoticon=emoji))
        return True
    except Exception:
        try:
            await c.send_read_acknowledge(ent, msg_id)
        except Exception:
            pass
        return False

async def do_react(c, ent, msg_id, emoji):
    if emoji and emoji.lower() in ["random", "rand", "r", "🍀"]:
        emoji = random.choice(RANDOM_EMOJIS)
    return await send_premium_reaction(c, ent, msg_id, emoji)

async def do_vote(c, ent, msg_id, btn_index, btn_text):
    msg = await c.get_messages(ent, ids=msg_id)
    if not msg.buttons:
        raise ValueError("No inline buttons on this post")
    btn, idx = None, 1
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
        return True
    except Exception:
        if btn.data:
            await c(GetBotCallbackAnswerRequest(
                peer=ent, msg_id=msg_id, data=btn.data))
            return True
        raise

async def do_poll_vote(c, ent, msg_id, poll_option_ids):
    msg = await c.get_messages(ent, ids=msg_id)
    if not msg.poll:
        raise ValueError("Not a poll")
    answers = msg.poll.poll.answers
    opts = []
    for i in poll_option_ids:
        if i < 0 or i >= len(answers):
            raise ValueError(f"Option {i} out of range (0-{len(answers)-1})")
        opts.append(answers[i].option)
    await c(SendVoteRequest(peer=ent, msg_id=msg_id, options=opts))
    return True

async def do_view(c, ent, msg_id):
    msg = await c.get_messages(ent, ids=msg_id)
    await c.send_read_acknowledge(ent, msg)
    return True

async def do_join(c, target):
    kind, val = target
    try:
        if kind == "username":
            await c(JoinChannelRequest(val))
        elif kind == "id":
            await c(JoinChannelRequest(await resolve_entity(c, target)))
        elif kind == "invite":
            await c(ImportChatInviteRequest(val))
        return True
    except UserAlreadyParticipantError:
        return True

async def do_leave(c, target):
    if target[0] == "invite":
        raise ValueError("Cannot leave via invite link")
    await c(LeaveChannelRequest(await resolve_entity(c, target)))
    return True

async def do_dm(c, target, text):
    if target[0] == "invite":
        raise ValueError("DM target must be @username or user id")
    ent = await resolve_entity(c, target) if target[0] == "username" else await c.get_entity(target[1])
    await c.send_message(ent, text)
    return True

async def run_campaign(uid, action, opts):
    # Count check karo
    count = int(opts.get("count", 0))
    if count <= 0:
        accs = my_accounts(uid) 
    else:
        accs = my_accounts(uid)[:count]
    
    if not accs:
        return 0, ["No accounts found or Limit reached."]
    
    random.shuffle(accs)
    st = get_settings(uid)
    ok, fail = 0, []
    
    post_ref, msg_id = opts.get("post_ref"), opts.get("msg_id")
    target, emoji = opts.get("target"), opts.get("emoji")
    bi, bt = opts.get("btn_index"), opts.get("btn_text")
    poll_options = opts.get("poll_options", [])
    
    ent = None
    if post_ref:
        first_acc = await get_client(accs[0])
        if first_acc is None:
            return 0, ["First account not available"]
        ent = await resolve_entity_cached(first_acc, post_ref)
        
    for acc in accs:
        try:
            c = await get_client(acc)
            if c is None:
                fail.append(f"{acc['phone']}: Session expired")
                continue
            if action in ("react", "react_vote", "react_vote_view"):
                if action == "react_vote_view":
                    await do_view(c, ent, msg_id)
                    await asyncio.sleep(random.uniform(1, 2))
                await do_react(c, ent, msg_id, emoji)
                if action != "react":
                    await asyncio.sleep(random.uniform(1, 2))
                    await do_vote(c, ent, msg_id, bi, bt)
            elif action == "vote":
                await do_vote(c, ent, msg_id, bi, bt)
            elif action == "poll_vote":
                if isinstance(poll_options, str):
                    poll_options = [int(x.strip()) for x in poll_options.split(',') if x.strip().isdigit()]
                await do_poll_vote(c, ent, msg_id, poll_options)
            elif action == "view":
                await do_view(c, ent, msg_id)
            elif action == "join":
                await do_join(c, target)
            elif action == "join_request":
                await do_join(c, target)
            elif action == "leave":
                await do_leave(c, target)
            elif action == "dm":
                await do_dm(c, target, opts["dm_text"])
            ok += 1
        except FloodWaitError as e:
            fail.append(f"{acc['phone']}: Flood wait {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 30))
        except Exception as e:
            fail.append(f"{acc['phone']}: {type(e).__name__}: {str(e)[:50]}")
        await asyncio.sleep(random.uniform(st["delay_min"], st["delay_max"]))
        
    campaigns.append({"owner": uid, "action": action, "ok": ok, "fail": len(fail),
                      "time": time.strftime("%d-%m %H:%M"), "total": len(accs)})
    save_campaigns()
    return ok, fail

async def scheduler_loop(bot):
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
#  BOT
# ==========================================================

bot = TelegramClient(os.path.join(config.SESSIONS_DIR, "control_bot"),
                     config.API_ID, config.API_HASH).start(bot_token=config.BOT_TOKEN)

ACTIONS = [
    ("react",           f"{PremiumEmojis.STAR} React"),
    ("vote",            f"{PremiumEmojis.VOTE} Vote"),
    ("poll_vote",       f"{PremiumEmojis.CHART} Poll Vote"),
    ("react_vote",      f"{PremiumEmojis.STAR} React + Vote"),
    ("view",            f"{PremiumEmojis.SEARCH} View"),
    ("react_vote_view", f"{PremiumEmojis.STAR} React + Vote + View"),
    ("join",            f"{PremiumEmojis.JOIN} Join"),
    ("join_request",    f"{PremiumEmojis.JOIN_CHANNEL} Join Request"),
    ("leave",           f"{PremiumEmojis.CANCEL} Leave"),
    ("dm",              f"{PremiumEmojis.SPEAKER} DM"),
]

MAIN_MENU = [
    [Button.inline(f"{PremiumEmojis.ID} My Account", b"myacc"),
     Button.inline(f"{PremiumEmojis.CONNECT} Add Account", b"add")],
    [Button.inline(f"{PremiumEmojis.CREATE} New Campaign", b"camp"),
     Button.inline(f"{PremiumEmojis.CHART} My Campaigns", b"mycamp")],
    [Button.inline(f"{PremiumEmojis.CALENDAR} Schedule", b"sched_info"),
     Button.inline(f"{PremiumEmojis.STATS} My Status", b"mystat")],
    [Button.inline(f"{PremiumEmojis.SETTINGS} Settings", b"set"),
     Button.inline(f"{PremiumEmojis.ADMIN} Owner Panel", b"owner_panel")],
    [Button.inline(f"{PremiumEmojis.CANCEL} Leave Channel", b"leave_menu"),
     Button.inline(f"{PremiumEmojis.SEARCH} Help", b"help")],
    [Button.inline(f"{PremiumEmojis.CLEAR} Remove Account", b"remove_acc")],
]

def menu_text(uid):
    my = len(my_accounts(uid))
    limit = get_user_limit(uid)
    limit_text = "Unlimited" if is_owner(uid) else (f"{limit}" if is_admin(uid) else "0")
    
    text = (f"{PremiumEmojis.CROWN} **╔═══ VOTEFLOW BOT ═══╗**\n\n"
            f"{PremiumEmojis.STATS} **Your Stats:**\n"
            f"┌──────────────────────┐\n"
            f"│ Your Accounts: **{my}**\n"
            f"│ Your Limit: **{limit_text}**\n"
            f"└──────────────────────┘\n\n"
            f"{PremiumEmojis.LOCK} **Access:** **{'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}**\n")
    
    # Global Stat sirf Owner ko dikhega
    if is_owner(uid):
        text += (f"{PremiumEmojis.CHART} **Global Stats:**\n"
                 f"Total Accounts: **{get_total_accounts()}**\n"
                 f"Total Users: **{len(set(a.get('owner') for a in accounts))}**\n")
    
    return text

def no_access():
    return (f"{PremiumEmojis.ALERT} **Access Denied!**\nOnly Owner/Admins can run campaigns.")

# ==========================================================
#  COMMANDS
# ==========================================================

@bot.on(events.NewMessage(pattern="^/(start|menu|help)$"))
async def cmd_start(e):
    reset(e.sender_id)
    await e.reply(menu_text(e.sender_id), buttons=MAIN_MENU, parse_mode="md")

@bot.on(events.NewMessage(pattern="^/me$"))
async def cmd_me(e):
    total, active, expired = await check_status(e.sender_id)
    await e.reply(f"{PremiumEmojis.ID} **My Profile**\n"
                  f"ID: `{e.sender_id}`\nAccounts: {total} | Active: {active} | Expired: {len(expired)}", parse_mode="md")

@bot.on(events.NewMessage(pattern="^/addadmin(@\w+)?(\s+.*)?$"))
async def cmd_addadmin(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Owner Only!", parse_mode="md")
    target_id = None
    if e.reply_to_msg_id:
        msg = await e.get_reply_message()
        target_id = msg.sender_id
    elif e.pattern_match.group(2):
        arg = e.pattern_match.group(2).strip()
        if arg.isdigit():
            target_id = int(arg)
        elif arg.startswith("@"):
            try:
                target_id = (await bot.get_entity(arg)).id
            except Exception:
                return await e.reply("❌ User not found.", parse_mode="md")
    if target_id is None:
        return await e.reply("Usage: `/addadmin <user_id>` or reply to user", parse_mode="md")
    if is_admin(target_id):
        return await e.reply(f"ℹ️ `{target_id}` is already admin.", parse_mode="md")
    admins.append(target_id)
    save_admins()
    await e.reply(f"✅ **`{target_id}` is now Admin!** (Limit: {config.ADMIN_ACCOUNT_LIMIT} accounts)", parse_mode="md")
    try:
        await bot.send_message(target_id, "🎉 You got **Admin access**! Use /start")
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
    if target_id not in admins:
        return await e.reply("ℹ️ This user is not admin.", parse_mode="md")
    admins.remove(target_id)
    save_admins()
    await e.reply(f"🗑️ Admin revoked for `{target_id}`.", parse_mode="md")

@bot.on(events.NewMessage(pattern="^/adminlist$"))
async def cmd_adminlist(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Owner Only!", parse_mode="md")
    if not admins:
        return await e.reply("No admins. Use: `/addadmin <id>`", parse_mode="md")
    lines = ["👮 **Admins:**"]
    for a in admins:
        try:
            u = await bot.get_entity(a)
            lines.append(f"· `{a}` — {u.first_name}")
        except Exception:
            lines.append(f"· `{a}` — (unknown)")
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

    # ── Owner Panel (Owner Only) ──
    if data == "owner_panel":
        if not is_owner(uid):
            return await e.answer("⛔ Owner Only!", alert=True)
        total_users = len(set(a.get("owner") for a in accounts))
        lines = [f"👑 **Owner Panel**\nGlobal Accounts: {len(accounts)}\nUsers: {total_users}\nAdmins: {len(admins)}"]
        if admins:
            lines.append("\n**Admins:**")
            for a in admins:
                try:
                    u = await bot.get_entity(a)
                    lines.append(f"· `{a}` — {u.first_name}")
                except Exception:
                    lines.append(f"· `{a}`")
        else:
            lines.append("· No admins")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    # ── My Account (With Expired details) ──
    if data == "myacc" or data == "profile":
        total, active, expired = await check_status(uid)
        accs = my_accounts(uid)
        lines = [f"🧑‍💼 **My Profile**\nID: `{uid}`\nAccess: **{'👑 Owner' if is_owner(uid) else ('✅ Admin' if is_admin(uid) else '👤 User')}**"]
        lines.append(f"📊 Accounts: {total} | Active: {active} | Expired: {len(expired)}")
        
        if accs:
            lines.append("\n**Active/Connected Accounts:**")
            for a in accs:
                if a["phone"] in clients:
                    lines.append(f"🟢 `{a['phone']}` — {a.get('name','?')}")
            
            if expired:
                lines.append("\n❌ **Expired/Failed Accounts:**")
                for exp in expired:
                    lines.append(f"🔴 `{exp}`")
        else:
            lines.append("\nNo accounts.")
            
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    # ── My Status (With Expired details) ──
    if data == "mystat":
        total, active, expired = await check_status(uid)
        myc = [c for c in campaigns if c["owner"] == uid]
        lines = [f"📊 **My Status**\nAccounts: {total} | Active: {active} | Expired: {len(expired)}",
                 f"Campaigns: {len(myc)} | Scheduled: {len([x for x in scheduled if x['owner']==uid])}"]
        if myc:
            lines.append("\n**Last 5:**")
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
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    # ── Help ──
    if data == "help":
        return await e.edit(
            "❓ **Help**\n\n"
            "**1. Add Account** — Phone+OTP / Session / Bulk\n"
            "**2. Access** — Only Owner/Admins run campaigns\n"
            "**3. Actions** — React, Vote, Poll Vote, View, Join, Leave, DM\n\n"
            "**Commands:**\n/start — Menu\n/me — Stats\n/addadmin — Add admin\n/rmadmin — Remove admin\n/adminlist — List admins",
            parse_mode="md", buttons=[[Button.inline("« Back", b"menu")]])

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

    # ── Schedule info ──
    if data == "sched_info":
        return await e.edit("📅 **Schedule**\nFormat: `30m` / `2h` / `1d`\nBot runs automatically.",
                            buttons=[[Button.inline("« Back", b"menu")]], parse_mode="md")

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

        if key == "poll_vote":
            s["step"] = "camp_post"
            s["poll_vote_mode"] = True
            return await e.edit("📊 **Poll Vote**\nSend poll URL:\n`https://t.me/...`",
                                buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

        if key in ("join", "join_request", "leave", "dm"):
            s["step"] = "camp_target"
            hints = {
                "join": "➕ **Join**\nSend: `@channel` or `https://t.me/+...`",
                "join_request": "📨 **Join Request**\nSend: `@channel` or `https://t.me/+...`",
                "leave": "🚪 **Leave**\nSend: `@channel` or chat id",
                "dm": "📩 **DM**\nSend: `@username` or user id",
            }
            return await e.edit(hints[key], buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

        s["step"] = "camp_post"
        return await e.edit("🔗 **Post URL**\nSend: `https://t.me/channel/123`\nor `https://t.me/c/1234567890/123`",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

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
        state(uid)["step"] = "camp_target"
        return await e.edit("🚪 Send @username or chat id:",
                            buttons=[[Button.inline("« Cancel", b"menu")]])

    if data == "list_chats":
        accs = my_accounts(uid)
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
                "camp_dm_text", "sched_time", "camp_poll_options"):
        if not is_admin(uid):
            reset(uid)
            return await e.reply(no_access())

    if step == "camp_post":
        parsed = parse_post_url(text)
        if not parsed:
            return await e.reply("❌ Invalid URL.", parse_mode="md")

        if s.get("poll_vote_mode"):
            s["camp_opts"] = {"post_ref": parsed[0], "msg_id": parsed[1]}
            s["step"] = "camp_poll_options"
            return await e.reply("📊 Send poll options (comma): `0,1,2`\n(0 = first option, 1 = second…)", parse_mode="md")

        s["camp_opts"] = {"post_ref": parsed[0], "msg_id": parsed[1]}
        action = s["camp_action"]
        
        # Count Step
        s["step"] = "camp_count"
        return await e.reply(f"🔢 How many accounts to use?\n(Available: {len(my_accounts(uid))} | 0 = Max Limit)", parse_mode="md")

    if step == "camp_count":
        if not text.isdigit():
            return await e.reply("❌ Send a number (e.g. `50`). `0` means max.", parse_mode="md")
        s["camp_opts"]["count"] = int(text)
        
        action = s["camp_action"]
        if action in ("react", "react_vote", "react_vote_view"):
            s["step"] = "camp_emoji"
            return await e.reply("😀 Send emoji: `👍` `❤️` `🔥` or `🍀` for random", parse_mode="md")
        if action == "vote":
            s["step"] = "camp_btn"
            return await e.reply("🗳️ Send button number or text:", parse_mode="md")
        return await ask_run(e, uid)

    if step == "camp_emoji":
        if not text.strip():
            return await e.reply("❌ Send an emoji!")
        s["camp_opts"]["emoji"] = text.strip()
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            s["step"] = "camp_btn"
            return await e.reply("🗳️ Send button (number or text):")
        return await ask_run(e, uid)

    if step == "camp_btn":
        if text.isdigit():
            s["camp_opts"]["btn_index"], s["camp_opts"]["btn_text"] = int(text), None
        else:
            s["camp_opts"]["btn_index"], s["camp_opts"]["btn_text"] = None, text
        return await ask_run(e, uid)

    if step == "camp_poll_options":
        options = [x.strip() for x in text.split(',') if x.strip().isdigit()]
        if not options:
            return await e.reply("❌ Invalid. Use: `0,1,2`", parse_mode="md")
        s["camp_opts"]["poll_options"] = [int(x) for x in options]
        return await ask_run(e, uid)

    if step == "camp_target":
        parsed = parse_target(text)
        if not parsed:
            return await e.reply("❌ Invalid target.", parse_mode="md")
        s["camp_opts"] = {"target": parsed}
        if s["camp_action"] == "dm":
            s["step"] = "camp_dm_text"
            return await e.reply("✉️ Send DM message:")
        return await ask_run(e, uid)

    if step == "camp_dm_text":
        s["camp_opts"]["dm_text"] = text
        return await ask_run(e, uid)

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
    s = state(uid)
    s["step"] = None
    label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
    opts = s.get("camp_opts", {})
    summary = f"🚀 **Campaign Ready**\n\nAction: **{label}**\n"
    if "post_ref" in opts:
        summary += f"Post ID: `{opts['msg_id']}`\n"
    if "count" in opts:
        summary += f"Accounts to use: `{opts['count']}` (0=Max)\n"
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
    summary += f"\n📊 Accounts: **{len(my_accounts(uid))}**"
    await e.reply(summary, parse_mode="md")
    await e.reply("▶️ Run now or schedule?",
                  buttons=[[Button.inline("▶️ Run Now", b"run_now"),
                            Button.inline("📅 Schedule", b"schedule_btn")],
                           [Button.inline("« Cancel", b"menu")]])

@bot.on(events.CallbackQuery(pattern=b"^schedule_btn$"))
async def sched_btn(e):
    if not is_admin(e.sender_id):
        return await e.answer(no_access(), alert=True)
    s = state(e.sender_id)
    s["step"] = "sched_time"
    await e.edit("📅 Send delay: `30m` / `2h` / `1d`",
                 buttons=[[Button.inline("« Cancel", b"menu")]])

# .txt file upload
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
    for acc in accounts:
        try:
            await get_client(acc)
        except Exception as ex:
            print(f"[load] {acc['phone']}: {ex}")
    asyncio.create_task(scheduler_loop(bot))
    print(f"[VoteFlow] Running. Accounts: {len(accounts)}, Admins: {len(admins)+1}, Scheduled: {len(scheduled)}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    bot.loop.run_until_complete(main())
