import asyncio
import json
import os
import random
import re
import threading
import time
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
    SendReactionRequest, GetMessagesViewsRequest
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
    ChatReactionsAll, ChatReactionsNone, ChatReactionsSome
)

try:
    from telethon.tl.types import KeyboardButtonCallback, KeyboardButtonStyle
    HAS_BTN_STYLE = True
except ImportError:
    HAS_BTN_STYLE = False

import config

os.makedirs(config.SESSIONS_DIR, exist_ok=True)
LOCK = threading.LOCK = threading.Lock()

# ── Support bot ref ──
CREDIT_BOT = "Aetherhu_bot"

# Timer-eligible actions
TIMER_ACTIONS = ("react", "react_vote", "react_vote_view", "vote",
                 "unvote", "poll_vote", "join", "join_request")

# ==========================================================
#  BOT INITIALIZATION - FIXED
# ==========================================================

bot = TelegramClient('bot', config.API_ID, config.API_HASH).start(bot_token=config.BOT_TOKEN)

# ==========================================================
#  UNICODE EMOJIS  —  Premium IDs only for reactions
# ==========================================================

class Emojis:
    VOTE       = "🎯"
    JOIN       = "✨"
    CANCEL     = "🚫"
    BACK       = "⬅️"
    CREATE     = "🚀"
    CONNECT    = "⛓️"
    MANAGE     = "💀"
    ADMIN      = "👑"
    STATS      = "📊"
    SETTINGS   = "⚙️"
    CLEAR      = "🧹"
    CHANNEL    = "📡"
    CONFIRM    = "✅"
    CHART      = "📈"
    ALERT      = "⚠️"
    SEARCH     = "👁️"
    SPEAKER    = "📢"
    LOCK       = "🔒"
    STAR       = "⭐"
    REQUEST    = "💌"
    CLOCK      = "⏰"
    TIMER      = "⏱️"
    FIRE       = "🔥"
    GEAR       = "⚙️"
    CROWN      = "👑"
    INFO       = "ℹ️"
    NEXT       = "▶️"
    SCHED      = "📅"
    LIST       = "📋"
    ID_BADGE   = "🆔"
    ROBOT      = "🤖"
    SUPPORT    = "🛟"

# Premium emoji IDs for reactions only
PREMIUM_EMOJI_IDS = {
    "❤️‍🔥": "6082544779223110894",
    "🌟": "6086784551894389168",
    "🎀": "6328086148274986212",
    "😎": "6334696528145286813",
    "🧊": "6057592848889418693",
    "🚩": "6082673701256434858",
    "👼": "6235505186157107501",
    "🧸": "6235332768989976110",
    "👶": "6129399728506412489",
    "💀": "6082160779082077008",
    "❤️": "5422842587151088042",
    "🔥": "6334449730734529256",
    "⭐": "6239815031219820750",
    "😭": "6042139181308657645",
    "👍": "6055469143992058889",
    "👎": "6057567104329974429",
    "😱": "6057777021055005214",
    "💔": "6057701214514186216",
}

def styled_btn(text, data, style=None):
    """Create a colorful inline button if Telethon supports it."""
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

def fancy(t: str) -> str:
    """Bold unicode converter."""
    _BOLD = str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘻"
        "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
        "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"
    )
    return str(t).translate(_BOLD)

# ==========================================================
#  PERSISTENCE & CLIENT MANAGEMENT
# ==========================================================

accounts: List[Dict] = []
clients: Dict[str, TelegramClient] = {}
admins: List[Dict] = []
settings: Dict[int, Dict] = {}
user_sessions: Dict[int, Dict] = {}
campaign_tasks: Dict[int, asyncio.Task] = {}
scheduled: List[Dict] = []
PENDING_STATE: Dict[int, Dict] = {}

def load_accounts():
    global accounts
    try:
        if os.path.exists(config.ACCOUNTS_FILE):
            with open(config.ACCOUNTS_FILE) as f:
                accounts = json.load(f)
    except Exception:
        accounts = []

def save_accounts():
    with LOCK:
        with open(config.ACCOUNTS_FILE, "w") as f:
            json.dump(accounts, f, indent=2)

def load_admins():
    global admins
    try:
        if os.path.exists(config.ADMINS_FILE):
            with open(config.ADMINS_FILE) as f:
                admins = json.load(f)
    except Exception:
        admins = []

def save_admins():
    with LOCK:
        with open(config.ADMINS_FILE, "w") as f:
            json.dump(admins, f, indent=2)

def load_settings():
    global settings
    try:
        if os.path.exists(config.SETTINGS_FILE):
            with open(config.SETTINGS_FILE) as f:
                settings = {int(k): v for k, v in json.load(f).items()}
    except Exception:
        settings = {}

def save_settings():
    with LOCK:
        with open(config.SETTINGS_FILE, "w") as f:
            json.dump({str(k): v for k, v in settings.items()}, f, indent=2)

def get_settings(uid: int) -> dict:
    st = settings.get(uid)
    if st is None:
        st = {"delay_min": 5.0, "delay_max": 10.0}
        settings[uid] = st
        save_settings()
    return st

def load_scheduled():
    global scheduled
    try:
        if os.path.exists(config.SCHEDULED_FILE):
            with open(config.SCHEDULED_FILE) as f:
                scheduled = json.load(f)
    except Exception:
        scheduled = []

def save_scheduled():
    with LOCK:
        with open(config.SCHEDULED_FILE, "w") as f:
            json.dump(scheduled, f, indent=2)

def state(uid: int) -> dict:
    if uid not in user_sessions:
        user_sessions[uid] = {}
    return user_sessions[uid]

def reset(uid: int):
    user_sessions.pop(uid, None)

def my_accounts(uid: int) -> list:
    return [a for a in accounts if a.get("owner") == uid]

def get_admin_accounts(uid: int) -> list:
    adm = next((a for a in admins if a["id"] == uid), None)
    if adm:
        lim = adm.get("limit", 0)
        if lim > 0:
            return my_accounts(uid)[:lim]
        return my_accounts(uid)
    return my_accounts(uid)

def is_owner(uid: int) -> bool:
    return uid in config.OWNER_IDS

def is_admin(uid: int) -> bool:
    return is_owner(uid) or any(a["id"] == uid for a in admins)

def no_access() -> str:
    return f"{Emojis.LOCK} Aap owner/admin nahi hain."

# ==========================================================
#  INVITE LINK PARSER
# ==========================================================

INVITE_RE = re.compile(
    r"(?:https?://)?t\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]{10,32})"
)

def parse_join_target(text: str) -> Optional[Tuple[str, str]]:
    text = text.strip()
    # Invite link
    m = INVITE_RE.search(text)
    if m:
        return ("invite", m.group(1))
    # @username
    if text.startswith("@"):
        return ("username", text[1:])
    # Plain username
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{3,30}", text):
        return ("username", text)
    # -100 numeric
    if re.fullmatch(r"-?100\d+", text):
        return ("id", text)
    if re.fullmatch(r"\d+", text):
        return ("id", "-100" + text)
    # Full https link
    m2 = re.search(r"t\.me/([a-zA-Z][a-zA-Z0-9_]{3,30})", text)
    if m2:
        return ("username", m2.group(1))
    return None

def parse_post_url(text: str) -> Optional[Tuple[str, int]]:
    text = text.strip()
    # Private: https://t.me/c/1234567890/123
    m = re.search(r"t\.me/c/(\d+)/(\d+)", text)
    if m:
        return (f"c{m.group(1)}", int(m.group(2)))
    # Public: https://t.me/channel/123
    m = re.search(r"t\.me/([a-zA-Z][a-zA-Z0-9_]{3,30})/(\d+)", text)
    if m:
        return (m.group(1), int(m.group(2)))
    # Just -100... / msg_id
    m = re.search(r"(-100\d+)\s*[/\s]*(\d+)", text)
    if m:
        return (m.group(1), int(m.group(2)))
    return None

async def resolve_entity_cached(client, ref: str):
    try:
        if ref[0] == "c":
            return await client.get_entity(PeerChannel(int(ref[1:])))
        if ref.startswith("-100"):
            return await client.get_entity(PeerChannel(int(ref)))
        if ref.startswith("@"):
            return await client.get_entity(ref)
        return await client.get_entity(ref)
    except Exception:
        return None

# ==========================================================
#  TIMER PARSER  — NEW: supports "batch_size gap"
# ==========================================================

def parse_timer(text: str) -> Optional[Tuple[int, int]]:
    """
    Returns (batch_size, gap_seconds) or None.
    Formats:
      "0"          -> (1, 0)       # no timer
      "30"         -> (1, 30)      # 1 acc per 30s
      "1m"         -> (1, 60)      # 1 acc per 1 min
      "2 1m"       -> (2, 60)      # 2 accs simultaneously, 1 min gap
      "5 30s"      -> (5, 30)      # 5 accs at once, 30s gap
      "10 2m"      -> (10, 120)    # 10 accs at once, 2 min gap
    """
    text = text.strip().lower()
    if text == "0":
        return (1, 0)

    parts = text.split()
    batch = 1
    gap_str = text

    if len(parts) == 2:
        # "batch gap" format
        if parts[0].isdigit():
            batch = int(parts[0])
            gap_str = parts[1]
        else:
            return None
    elif len(parts) > 2:
        return None

    # Parse gap
    m = re.fullmatch(r"(\d+)([smhd])?", gap_str)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2) or "s"
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 1)
    gap = val * mult
    if gap < 0:
        return None
    return (batch, gap)


def fmt_timer(timer: Tuple[int, int]) -> str:
    batch, gap = timer
    if gap == 0:
        return "No Timer"
    parts = []
    if batch > 1:
        parts.append(f"{batch} accounts together")
    if gap >= 3600:
        parts.append(f"every {gap//3600}h")
    elif gap >= 60:
        parts.append(f"every {gap//60}m")
    else:
        parts.append(f"every {gap}s")
    return ", ".join(parts) if parts else "0"


# ==========================================================
#  CAMPAIGN RUNNER
# ==========================================================

async def run_campaign(owner: int, opts: dict):
    """Execute a campaign with optional batched timer."""
    action = opts.get("action", "react")
    accounts_list = get_admin_accounts(owner) if is_admin(owner) else my_accounts(owner)
    total = opts.get("count", 0) or len(accounts_list)
    accounts_use = accounts_list[:min(total, len(accounts_list))]

    if not accounts_use:
        await bot.send_message(owner, f"{Emojis.ALERT} No accounts available.")
        return

    timer = opts.get("timer", (1, 0))  # (batch_size, gap_seconds)
    batch_size, gap = timer

    results = {"ok": 0, "fail": 0, "total": len(accounts_use), "failures": []}
    campaign_id = int(time.time())

    # ── Join private channel first if needed ──
    join_target = opts.get("join_target")
    if join_target:
        for idx, acc in enumerate(accounts_use):
            if acc.get("_skip"):
                continue
            c = await get_client(acc)
            if not c:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: dead client")
                continue
            try:
                if join_target[0] == "invite":
                    updates = await c(ImportChatInviteRequest(join_target[1]))
                    peer = updates.chats[0].id
                else:
                    entity = await c.get_entity(join_target[1])
                    peer = entity.id
                    await c(JoinChannelRequest(entity))
                r = await c(GetFullChannelRequest(peer))
                peer = r.full_chat.id
                opts["_peer"] = peer
                results["ok"] += 1
            except UserAlreadyParticipantError:
                try:
                    entity = await c.get_entity(join_target[1])
                    r = await c(GetFullChannelRequest(entity))
                    opts["_peer"] = r.full_chat.id
                except Exception:
                    pass
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: join fail {str(ex)[:40]}")

        if join_target[0] == "invite":
            await asyncio.sleep(3)  # let membership propagate

    # ── Main campaign loop (batched) ──
    for batch_start in range(0, len(accounts_use), batch_size):
        batch = accounts_use[batch_start:batch_start + batch_size]
        tasks = []
        for acc in batch:
            if acc.get("_skip"):
                continue
            tasks.append(_run_single(acc, action, opts, results, campaign_id))

        # Run batch concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Gap between batches
        if gap > 0 and batch_start + batch_size < len(accounts_use):
            remaining = len(accounts_use) - (batch_start + batch_size)
            next_batch_size = min(batch_size, remaining)
            log_info = f"[campaign] timer: waiting {gap}s, next batch = {next_batch_size} accounts"
            print(log_info)
            try:
                async with bot.action(owner, "typing"):
                    await asyncio.sleep(gap)
            except Exception:
                await asyncio.sleep(gap)

    # ── Report ──
    ok, fail, total, failures = results["ok"], results["fail"], results["total"], results["failures"]
    label = dict(ACTIONS).get(action, action)
    msg = (
        f"{Emojis.CHART} **{fancy('CAMPAIGN COMPLETE')}**\n\n"
        f"Action: **{label}**\n"
        f"Accounts: **{ok}/{total}**"
    )
    if fail:
        msg += f"\nFailed: **{fail}**"
    if failures:
        msg += "\n\n" + "\n".join(f"❌ {f[:80]}" for f in failures[:5])
        if len(failures) > 5:
            msg += f"\n...and {len(failures)-5} more"

    # Check for views comparison
    v_before = opts.get("views_before")
    v_final = opts.get("views_final")
    if v_before is not None and v_final is not None:
        msg += f"\n\n{Emojis.CHART} Views: **{v_before} → {v_final}**"

    await bot.send_message(owner, msg)


async def _run_single(acc: dict, action: str, opts: dict, results: dict, campaign_id: int):
    """Execute one account's action."""
    try:
        c = await get_client(acc)
        if not c:
            results["fail"] += 1
            results["failures"].append(f"{acc.get('phone','?')}: no client")
            return

        peer = opts.get("_peer")
        msg_id = opts.get("msg_id")
        emoji = opts.get("emoji", "❤️")
        btn_index = opts.get("btn_index")
        btn_text = opts.get("btn_text")
        post_ref = opts.get("post_ref")
        target = opts.get("target")
        dm_text = opts.get("dm_text", "")
        poll_options = opts.get("poll_options", [])

        # ── REACT ──
        if action == "react":
            if not post_ref or not msg_id:
                results["fail"] += 1
                return
            entity = await resolve_entity_cached(c, post_ref)
            if not entity:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: resolve fail {post_ref}")
                return
            try:
                actual_emoji = random.choice(list(PREMIUM_EMOJI_IDS.keys())) if emoji.lower() in ("random","rand","r","🍀") else emoji
                custom_id = PREMIUM_EMOJI_IDS.get(actual_emoji)
                if custom_id:
                    await c(SendReactionRequest(
                        peer=entity,
                        msg_id=msg_id,
                        reaction=[ReactionCustomEmoji(document_id=int(custom_id))]
                    ))
                else:
                    await c(SendReactionRequest(
                        peer=entity,
                        msg_id=msg_id,
                        reaction=[ReactionEmoji(emoticon=actual_emoji)]
                    ))
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: react {str(ex)[:40]}")

        # ── REACT + VOTE ──
        elif action == "react_vote":
            if not post_ref or not msg_id:
                results["fail"] += 1
                return
            entity = await resolve_entity_cached(c, post_ref)
            if not entity:
                results["fail"] += 1
                return
            try:
                actual_emoji = random.choice(list(PREMIUM_EMOJI_IDS.keys())) if emoji.lower() in ("random","rand","r","🍀") else emoji
                custom_id = PREMIUM_EMOJI_IDS.get(actual_emoji)
                if custom_id:
                    await c(SendReactionRequest(
                        peer=entity, msg_id=msg_id,
                        reaction=[ReactionCustomEmoji(document_id=int(custom_id))]
                    ))
                else:
                    await c(SendReactionRequest(
                        peer=entity, msg_id=msg_id,
                        reaction=[ReactionEmoji(emoticon=actual_emoji)]
                    ))
            except Exception:
                pass
            try:
                post = await c.get_messages(entity, ids=msg_id)
                if post and post.buttons:
                    btn = None
                    if btn_index and btn_index <= len(post.buttons):
                        for row in post.buttons:
                            for b in row:
                                if b.text == (btn_text or str(btn_index)):
                                    btn = b
                                    break
                            else:
                                continue
                            break
                    if btn:
                        await btn.click()
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: react+vote {str(ex)[:40]}")

        # ── REACT + VOTE + VIEWS ──
        elif action == "react_vote_view":
            if not post_ref or not msg_id:
                results["fail"] += 1
                return
            entity = await resolve_entity_cached(c, post_ref)
            if not entity:
                results["fail"] += 1
                return
            try:
                actual_emoji = random.choice(list(PREMIUM_EMOJI_IDS.keys())) if emoji.lower() in ("random","rand","r","🍀") else emoji
                custom_id = PREMIUM_EMOJI_IDS.get(actual_emoji)
                if custom_id:
                    await c(SendReactionRequest(
                        peer=entity, msg_id=msg_id,
                        reaction=[ReactionCustomEmoji(document_id=int(custom_id))]
                    ))
                else:
                    await c(SendReactionRequest(
                        peer=entity, msg_id=msg_id,
                        reaction=[ReactionEmoji(emoticon=actual_emoji)]
                    ))
            except Exception:
                pass
            try:
                post = await c.get_messages(entity, ids=msg_id)
                if post and post.buttons:
                    btn = None
                    if btn_index and btn_index <= len(post.buttons):
                        for row in post.buttons:
                            for b in row:
                                if b.text == (btn_text or str(btn_index)):
                                    btn = b
                                    break
                            else:
                                continue
                            break
                    if btn:
                        await btn.click()
            except Exception:
                pass
            try:
                await c(GetMessagesViewsRequest(
                    peer=entity, id=[msg_id], increment=True
                ))
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: views {str(ex)[:40]}")

        # ── VOTE / UNVOTE ──
        elif action in ("vote", "unvote"):
            if not post_ref or not msg_id:
                results["fail"] += 1
                return
            entity = await resolve_entity_cached(c, post_ref)
            if not entity:
                results["fail"] += 1
                return
            try:
                post = await c.get_messages(entity, ids=msg_id)
                if post and post.buttons:
                    btn = None
                    if btn_index and btn_index <= len(post.buttons):
                        for row in post.buttons:
                            for b in row:
                                if b.text == (btn_text or str(btn_index)):
                                    btn = b
                                    break
                            else:
                                continue
                            break
                    if btn:
                        if action == "unvote":
                            # Re-click toggles the vote off
                            await btn.click()
                        else:
                            await btn.click()
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: vote {str(ex)[:40]}")

        # ── POLL VOTE ──
        elif action == "poll_vote":
            if not post_ref or not msg_id or not poll_options:
                results["fail"] += 1
                return
            entity = await resolve_entity_cached(c, post_ref)
            if not entity:
                results["fail"] += 1
                return
            try:
                post = await c.get_messages(entity, ids=msg_id)
                if post and post.poll:
                    for opt in poll_options:
                        if opt < len(post.poll.poll.answers):
                            await c(SendVoteRequest(
                                peer=entity, msg_id=msg_id,
                                options=[post.poll.poll.answers[opt].option]
                            ))
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: poll {str(ex)[:40]}")

        # ── VIEWS ──
        elif action == "views":
            if not post_ref or not msg_id:
                results["fail"] += 1
                return
            entity = await resolve_entity_cached(c, post_ref)
            if not entity:
                results["fail"] += 1
                return
            try:
                await c(GetMessagesViewsRequest(
                    peer=entity, id=[msg_id], increment=True
                ))
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: views {str(ex)[:40]}")

        # ── JOIN ──
        elif action == "join":
            if not target:
                results["fail"] += 1
                return
            try:
                if target[0] == "invite":
                    await c(ImportChatInviteRequest(target[1]))
                elif target[0] == "username":
                    entity = await c.get_entity(target[1])
                    await c(JoinChannelRequest(entity))
                elif target[0] == "id":
                    await c(JoinChannelRequest(PeerChannel(int(target[1]))))
                results["ok"] += 1
            except UserAlreadyParticipantError:
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: join {str(ex)[:40]}")

        # ── JOIN REQUEST ──
        elif action == "join_request":
            if not target:
                results["fail"] += 1
                return
            try:
                if target[0] == "invite":
                    await c(ImportChatInviteRequest(target[1]))
                elif target[0] == "username":
                    entity = await c.get_entity(target[1])
                    await c(JoinChannelRequest(entity))
                elif target[0] == "id":
                    await c(JoinChannelRequest(PeerChannel(int(target[1]))))
                # If it's a group with join request, it may raise or need approval
                # We just attempt join
                results["ok"] += 1
            except UserAlreadyParticipantError:
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: join_req {str(ex)[:40]}")

        # ── LEAVE ──
        elif action == "leave":
            if not target:
                results["fail"] += 1
                return
            try:
                if target[0] == "username":
                    entity = await c.get_entity(target[1])
                    await c(LeaveChannelRequest(entity))
                elif target[0] == "id":
                    await c(LeaveChannelRequest(PeerChannel(int(target[1]))))
                elif target[0] == "invite":
                    # Can't leave by invite; resolve first
                    try:
                        chat = await c(CheckChatInviteRequest(target[1]))
                        if hasattr(chat, 'chat'):
                            await c(LeaveChannelRequest(chat.chat))
                    except Exception:
                        pass
                results["ok"] += 1
            except UserNotParticipantError:
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: leave {str(ex)[:40]}")

        # ── DM ──
        elif action == "dm":
            if not target:
                results["fail"] += 1
                return
            try:
                if target[0] == "username":
                    entity = await c.get_entity(target[1])
                else:
                    entity = await c.get_entity(int(target[1]))
                await c.send_message(entity, dm_text)
                results["ok"] += 1
            except Exception as ex:
                results["fail"] += 1
                results["failures"].append(f"{acc.get('phone','?')}: dm {str(ex)[:40]}")

        else:
            results["fail"] += 1
            results["failures"].append(f"{acc.get('phone','?')}: unknown action {action}")

    except asyncio.CancelledError:
        raise
    except Exception as ex:
        results["fail"] += 1
        results["failures"].append(f"{acc.get('phone','?')}: {str(ex)[:60]}")


# ==========================================================
#  CLIENT GETTER / SESSION SAVE
# ==========================================================

async def get_client(acc: dict) -> Optional[TelegramClient]:
    phone = acc.get("phone", "")
    if phone in clients:
        c = clients[phone]
        if c.is_connected():
            return c
        try:
            await c.connect()
            return c
        except Exception:
            pass
    session_str = acc.get("session", "")
    if not session_str:
        return None
    try:
        c = TelegramClient(StringSession(session_str), config.API_ID, config.API_HASH)
        await c.connect()
        if not await c.is_user_authorized():
            await c.disconnect()
            return None
        clients[phone] = c
        return c
    except Exception as ex:
        print(f"[client] Error for {phone}: {str(ex)[:60]}")
        return None

async def save_session_account(client: TelegramClient, owner: int) -> dict:
    me = await client.get_me()
    session_str = StringSession.save(client.session)
    phone = f"+{me.phone}" if me.phone else f"+{me.id}"
    acc = {"phone": phone, "session": session_str, "name": f"{me.first_name or ''} {me.last_name or ''}".strip(),
           "owner": owner, "premium": getattr(me, 'premium', False)}
    accounts.append(acc)
    save_accounts()
    client_str = os.path.join(config.SESSIONS_DIR, phone.lstrip("+") + ".session")
    # We no longer write .session files; everything is in accounts.json
    return acc

async def validate_session_string(session_str: str, owner: int) -> dict:
    c = TelegramClient(StringSession(session_str), config.API_ID, config.API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        raise ValueError("Session expired")
    return await save_session_account(c, owner)

# ==========================================================
#  CAMPAIGN CANCEL / STOP
# ==========================================================

@bot.on(events.CallbackQuery(pattern=b"^stop_campaign$"))
async def stop_campaign(e):
    if not is_admin(e.sender_id):
        return await e.answer(no_access(), alert=True)
    task = campaign_tasks.get(e.sender_id)
    if task and not task.done():
        task.cancel()
        campaign_tasks.pop(e.sender_id, None)
        await e.edit(f"{Emojis.CLEAR} Campaign cancelled.", buttons=None)
    else:
        await e.answer("No running campaign.", alert=True)

# ==========================================================
#  BOT START / MENU
# ==========================================================

ACTIONS = [
    ("react", f"{Emojis.FIRE} React"),
    ("react_vote", f"{Emojis.VOTE} React + Vote"),
    ("react_vote_view", f"{Emojis.VOTE} React + Vote + Views"),
    ("vote", f"{Emojis.VOTE} Vote"),
    ("unvote", f"{Emojis.CLEAR} Unvote"),
    ("poll_vote", f"{Emojis.CHART} Poll Vote"),
    ("views", f"{Emojis.CHART} Views"),
    ("join", f"{Emojis.JOIN} Join"),
    ("join_request", f"{Emojis.REQUEST} Join Request"),
    ("leave", f"{Emojis.CLEAR} Leave"),
    ("dm", f"{Emojis.REQUEST} DM"),
]

MAIN_MENU = [
    [styled_btn(f"{Emojis.CREATE} Create Campaign", b"create_campaign", "primary")],
    [Button.inline(f"{Emojis.CONNECT} Add Account", b"add")],
    [Button.inline(f"{Emojis.LIST} My Accounts", b"list")],
    [styled_btn(f"{Emojis.SETTINGS} Settings", b"settings", "primary")],
    [Button.inline(f"{Emojis.SCHED} Scheduled", b"scheduled")],
    [Button.url(f"{Emojis.SUPPORT} Support", f"https://t.me/{CREDIT_BOT}")],
]

@bot.on(events.NewMessage(pattern="^/start$"))
async def start(e):
    uid = e.sender_id
    reset(uid)
    is_adm = is_admin(uid)
    owner_flag = is_owner(uid)

    if is_adm:
        acc_count = len(my_accounts(uid))
        if owner_flag:
            role = f"{Emojis.CROWN} **Owner**"
        else:
            role = f"{Emojis.ADMIN} **Admin**"
        await e.reply(
            f"{Emojis.ROBOT} **{fancy('VOTEFLOW')}** — Telegram Automation\n\n"
            f"👤 **User:** `{uid}`\n"
            f"🎖️ **Role:** {role}\n"
            f"📦 **Accounts:** `{acc_count}`\n"
            f"{Emojis.INFO} Tap **Create Campaign** to start.\n\n"
            f"{Emojis.SUPPORT} **Support:** @{CREDIT_BOT}",
            buttons=MAIN_MENU, parse_mode="md"
        )
    else:
        await e.reply(
            f"{Emojis.ROBOT} **{fancy('VOTEFLOW')}**\n\n"
            f"{Emojis.LOCK} Aap owner/admin nahi hain.\n"
            f"{Emojis.SUPPORT} Contact: @{CREDIT_BOT}",
            buttons=[[Button.url(f"{Emojis.SUPPORT} Support", f"https://t.me/{CREDIT_BOT}")]],
            parse_mode="md"
        )

@bot.on(events.NewMessage(pattern="^/me$"))
async def me(e):
    uid = e.sender_id
    owner_flag = is_owner(uid)
    adm = is_admin(uid)
    accs = len(my_accounts(uid))
    role = f"{Emojis.CROWN} Owner" if owner_flag else (f"{Emojis.ADMIN} Admin" if adm else "User")
    await e.reply(
        f"{Emojis.ROBOT} **{fancy('YOUR INFO')}**\n\n"
        f"🆔 **ID:** `{uid}`\n"
        f"🎖️ **Role:** {role}\n"
        f"📦 **Accounts:** `{accs}`\n"
        f"{Emojis.SUPPORT} **Support:** @{CREDIT_BOT}",
        parse_mode="md"
    )

@bot.on(events.NewMessage(pattern="^/list$"))
async def list_cmd(e):
    if not is_admin(e.sender_id):
        return await e.reply(no_access())
    accs = my_accounts(e.sender_id)
    if not accs:
        return await e.reply(f"{Emojis.ALERT} No accounts.")
    lines = [f"{Emojis.LIST} **{fancy('YOUR ACCOUNTS')}**"]
    for i, a in enumerate(accs, 1):
        prem = "⭐" if a.get("premium") else ""
        lines.append(f"{i}. `{a['phone']}` {prem} — {a.get('name','?')}")
    await e.reply("\n".join(lines), parse_mode="md")

@bot.on(events.NewMessage(pattern="^/check (\\d+)$"))
async def check_cmd(e):
    if not is_owner(e.sender_id):
        return await e.reply(no_access())
    target_id = int(e.pattern_match.group(1))
    adm = next((a for a in admins if a["id"] == target_id), None)
    accs = my_accounts(target_id)
    await e.reply(
        f"{Emojis.SEARCH} **{fancy('USER LOOKUP')}**\n\n"
        f"🆔 **ID:** `{target_id}`\n"
        f"🎖️ **Admin:** {'Yes' if adm else 'No'}\n"
        f"📦 **Accounts:** `{len(accs)}`\n"
        f"🔢 **Limit:** `{adm.get('limit', 'N/A') if adm else 'N/A'}`",
        parse_mode="md"
    )

# ==========================================================
#  CALLBACK QUERY HANDLER (main navigation)
# ==========================================================

@bot.on(events.CallbackQuery)
async def callback_handler(e):
    data = e.data
    uid = e.sender_id

    # ── Menu ──
    if data == b"menu":
        reset(uid)
        is_adm = is_admin(uid)
        if is_adm:
            acc_count = len(my_accounts(uid))
            role = f"{Emojis.CROWN} Owner" if is_owner(uid) else f"{Emojis.ADMIN} Admin"
            await e.edit(
                f"{Emojis.ROBOT} **{fancy('VOTEFLOW')}** — Telegram Automation\n\n"
                f"👤 **User:** `{uid}`\n"
                f"🎖️ **Role:** {role}\n"
                f"📦 **Accounts:** `{acc_count}`\n"
                f"{Emojis.SUPPORT} **Support:** @{CREDIT_BOT}",
                buttons=MAIN_MENU, parse_mode="md"
            )
        else:
            await e.edit(
                f"{Emojis.ROBOT} **{fancy('VOTEFLOW')}**\n\n{Emojis.LOCK} No access.\n"
                f"{Emojis.SUPPORT} @{CREDIT_BOT}",
                buttons=[[Button.url(f"{Emojis.SUPPORT} Support", f"https://t.me/{CREDIT_BOT}")]],
                parse_mode="md"
            )
        return

    # ── Create Campaign ──
    if data == b"create_campaign":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        rows, row = [], []
        for i, (act, label) in enumerate(ACTIONS, 1):
            row.append(Button.inline(label, f"action:{act}".encode()))
            if i % 2 == 0:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")])
        await e.edit(
            f"{Emojis.VOTE} **{fancy('SELECT ACTION')}**",
            buttons=rows, parse_mode="md"
        )
        return

    # ── Action selection ──
    if data.startswith(b"action:"):
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        action = data.decode().split(":", 1)[1]
        s = state(uid)
        s["camp_action"] = action
        s["camp_opts"] = {}

        if action in ("react", "react_vote", "react_vote_view", "vote", "unvote", "poll_vote", "views"):
            await e.edit(
                f"{Emojis.CHANNEL} **{fancy('SEND POST URL')}**\n\n"
                f"Public: `https://t.me/channel/123`\n"
                f"Private: `https://t.me/c/1234567890/123`\n\n"
                f"Or: `-1001234567890/123`",
                buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]],
                parse_mode="md"
            )
            s["step"] = "camp_post"
            return

        if action in ("join", "join_request", "leave", "dm"):
            await e.edit(
                f"{Emojis.TARGET} **{fancy('SEND TARGET')}**\n\n"
                f"Username: `@channel`\nInvite: `https://t.me/+hash`\nID: `-100123`",
                buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]],
                parse_mode="md"
            )
            s["step"] = "camp_target"
            return

        return

    # ── Add Account ──
    if data == b"add":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        s = state(uid)
        s["step"] = None
        await e.edit(
            f"{Emojis.CONNECT} **{fancy('ADD ACCOUNT')}**\n\n"
            f"1️⃣ Phone: `+919876543210`\n"
            f"2️⃣ String Session: paste long string\n"
            f"3️⃣ Bulk: upload `.txt` file (one session per line)\n\n"
            f"Send phone (with country code) or session string.",
            buttons=[
                [Button.inline(f"{Emojis.CONFIRM} String Session", b"add_string")],
                [Button.inline(f"{Emojis.REQUEST} Bulk Upload", b"add_bulk")],
                [Button.inline(f"{Emojis.BACK} Back", b"menu")],
            ], parse_mode="md"
        )
        return

    if data == b"add_string":
        s = state(uid)
        s["step"] = "add_string_input"
        await e.edit("Send your **String Session**:", parse_mode="md")
        return

    if data == b"add_bulk":
        s = state(uid)
        s["step"] = "bulk_input"
        await e.edit(
            f"{Emojis.REQUEST} Send a `.txt` file with one String Session per line.\n"
            f"Or paste sessions directly (one per line).",
            parse_mode="md"
        )
        return

    # ── List Accounts ──
    if data == b"list":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        accs = my_accounts(uid)
        if not accs:
            return await e.edit(f"{Emojis.ALERT} No accounts.", buttons=[[Button.inline(f"{Emojis.BACK} Back", b"menu")]])
        rows = []
        for i, a in enumerate(accs, 1):
            prem = "⭐" if a.get("premium") else ""
            rows.append([Button.inline(
                f"{i}. {a['phone']} {prem}",
                f"accinfo:{i}".encode()
            )])
        rows.append([Button.inline(f"{Emojis.BACK} Back", b"menu")])
        await e.edit(
            f"{Emojis.LIST} **{fancy('YOUR ACCOUNTS')}** — tap to remove",
            buttons=rows, parse_mode="md"
        )
        return

    # ── Account Info / Remove ──
    if data.startswith(b"accinfo:"):
        idx = int(data.decode().split(":", 1)[1])
        accs = my_accounts(uid)
        if idx < 1 or idx > len(accs):
            return await e.answer("Invalid", alert=True)
        acc = accs[idx - 1]
        phone = acc["phone"]
        await e.edit(
            f"{Emojis.SEARCH} **{fancy('ACCOUNT')}**\n\n"
            f"📞 **Phone:** `{phone}`\n"
            f"👤 **Name:** {acc.get('name','?')}\n"
            f"⭐ **Premium:** {'Yes' if acc.get('premium') else 'No'}\n",
            buttons=[
                [styled_btn(f"{Emojis.CLEAR} Remove", f"remove:{idx}".encode(), "danger")],
                [Button.inline(f"{Emojis.BACK} Back", b"list")],
            ], parse_mode="md"
        )
        return

    if data.startswith(b"remove:"):
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        idx = int(data.decode().split(":", 1)[1])
        accs = my_accounts(uid)
        if idx < 1 or idx > len(accs):
            return await e.answer("Invalid", alert=True)
        acc = accs[idx - 1]
        phone = acc["phone"]
        c = clients.pop(phone, None)
        if c:
            await c.disconnect()
        accounts.remove(acc)
        save_accounts()
        p = os.path.join(config.SESSIONS_DIR, phone.lstrip("+") + ".session")
        if os.path.exists(p):
            os.remove(p)
        await e.edit(f"{Emojis.CLEAR} Removed `{phone}`",
                     buttons=[[Button.inline(f"{Emojis.BACK} Back", b"list")]],
                     parse_mode="md")
        return

    # ── Settings ──
    if data == b"settings":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        st = get_settings(uid)
        await e.edit(
            f"{Emojis.SETTINGS} **{fancy('SETTINGS')}**\n\n"
            f"⏱️ Delay Range: **{st['delay_min']}s – {st['delay_max']}s**\n"
            f"(random delay between each action)\n\n"
            f"Send new range as: `min-max`\nExample: `2-7`",
            buttons=[[Button.inline(f"{Emojis.BACK} Back", b"menu")]],
            parse_mode="md"
        )
        s = state(uid)
        s["step"] = "set"
        return

    # ── Scheduled ──
    if data == b"scheduled":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        if not scheduled:
            return await e.edit(f"{Emojis.ALERT} No scheduled campaigns.",
                                buttons=[[Button.inline(f"{Emojis.BACK} Back", b"menu")]])
        lines = [f"{Emojis.SCHED} **{fancy('SCHEDULED CAMPAIGNS')}**"]
        for i, sc in enumerate(scheduled, 1):
            due = sc.get("due_at", 0)
            remaining = max(0, due - time.time())
            lines.append(
                f"{i}. {dict(ACTIONS).get(sc.get('action','?'), sc.get('action','?'))} — "
                f"in {int(remaining//60)}m"
            )
        lines.append(f"\n{Emojis.INFO} `{len(scheduled)}` pending")
        await e.edit("\n".join(lines),
                     buttons=[[Button.inline(f"{Emojis.CLEAR} Clear All", b"clear_sched")],
                              [Button.inline(f"{Emojis.BACK} Back", b"menu")]],
                     parse_mode="md")
        return

    if data == b"clear_sched":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        scheduled.clear()
        save_scheduled()
        await e.edit(f"{Emojis.CLEAR} All scheduled cleared.",
                     buttons=[[Button.inline(f"{Emojis.BACK} Back", b"menu")]])
        return

    # ── Timer "No Timer" ──
    if data == b"timer_off":
        s = state(uid)
        s.setdefault("camp_opts", {})["timer"] = (1, 0)
        await e.answer("Timer disabled — all accounts will run instantly.")
        await camp_next(e, uid)
        return

    # ── Run Now ──
    if data == b"run_now":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        s = state(uid)
        opts = s.get("camp_opts", {})
        opts["action"] = s.get("camp_action", "react")

        # Default timer = (1, 0) i.e. no timer
        if "timer" not in opts:
            opts["timer"] = (1, 0)

        # Views: capture before count
        if opts["action"] == "views":
            post_ref = opts.get("post_ref")
            msg_id = opts.get("msg_id")
            if post_ref and msg_id:
                accs = get_admin_accounts(uid)
                if accs:
                    c = await get_client(accs[0])
                    if c:
                        entity = await resolve_entity_cached(c, post_ref)
                        if entity:
                            try:
                                msgs = await c(GetMessagesRequest(entity, ids=[msg_id]))
                                if msgs.messages:
                                    opts["views_before"] = msgs.messages[0].views
                            except Exception:
                                pass

        task = asyncio.create_task(run_and_clean(uid, opts))
        campaign_tasks[uid] = task
        reset(uid)
        await e.edit(f"{Emojis.NEXT} Campaign started! Use /stop to cancel.",
                     buttons=[[Button.inline(f"{Emojis.CLEAR} Stop Campaign", b"stop_campaign")]])
        return

    # ── Schedule ──
    if data == b"do_schedule":
        if not is_admin(uid):
            return await e.answer(no_access(), alert=True)
        s = state(uid)
        delay = s.get("sched_delay", 300)
        opts = s.get("camp_opts", {}).copy()
        opts["action"] = s.get("camp_action", "react")
        if "timer" not in opts:
            opts["timer"] = (1, 0)
        schedule_entry = {
            "owner": uid,
            "action": opts["action"],
            "opts": opts,
            "due_at": time.time() + delay,
        }
        scheduled.append(schedule_entry)
        save_scheduled()
        await e.edit(f"{Emojis.SCHED} Campaign scheduled in **{delay//60}m**.",
                     buttons=MAIN_MENU, parse_mode="md")
        reset(uid)
        return

    # ── React: specific or random ──
    if data == b"react_specific":
        s = state(uid)
        s["step"] = "camp_emoji"
        await e.edit(f"{Emojis.STAR} Send reaction emoji:\nExample: `❤️` `🔥` `👍`\n\n💡 Premium accounts can use any emoji.",
                     buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])
        return

    if data == b"react_random":
        s = state(uid)
        s["camp_opts"]["emoji"] = "random"
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            await e.edit(f"{Emojis.VOTE} Button number:\n`1` / `Vote Now`",
                         buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])
            s["step"] = "camp_btn"
        else:
            await ask_run(e, uid)
        return

    # ── Pick button from preview ──
    if data.startswith(b"pickbtn:"):
        s = state(uid)
        btn_idx = int(data.decode().split(":", 1)[1])
        btns = s.get("post_btns", [])
        if btn_idx < 1 or btn_idx > len(btns):
            return await e.answer("Invalid button.", alert=True)
        s["camp_opts"]["btn_index"] = btn_idx
        s["camp_opts"]["btn_text"] = None
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            s["step"] = "camp_emoji"
            await e.edit(f"{Emojis.STAR} Now send reaction emoji:\nExample: `❤️`",
                         buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])
        else:
            await ask_run(e, uid)
        return

    await e.answer("Unknown button.", alert=True)

async def run_and_clean(uid: int, opts: dict):
    try:
        await run_campaign(uid, opts)
    except asyncio.CancelledError:
        await bot.send_message(uid, f"{Emojis.CLEAR} Campaign cancelled.")
    except Exception as ex:
        await bot.send_message(uid, f"{Emojis.ALERT} Campaign error: {str(ex)[:100]}")
    finally:
        campaign_tasks.pop(uid, None)

# ==========================================================
#  TEXT HANDLER — all step-based input
# ==========================================================

async def steps(e):
    uid = e.sender_id
    if not is_admin(uid):
        return
    s = state(uid)
    step = s.get("step")
    if not step:
        return

    text = (e.text or "").strip()

    # Phone + OTP
    if step == "add_phone_number":
        if not re.fullmatch(r"\+\d{6,15}", text):
            return await e.reply(f"{Emojis.ALERT} Invalid format. Example: `+919876543210`", parse_mode="md")
        s["phone"] = text
        client = TelegramClient(os.path.join(config.SESSIONS_DIR, text.lstrip("+")),
                                config.API_ID, config.API_HASH)
        await client.connect()
        sent = await client.send_code_request(text)
        s["phone_code_hash"] = sent.phone_code_hash
        s["client"] = client
        s["step"] = "add_phone_otp"
        return await e.reply(f"{Emojis.CONFIRM} Code sent! Send OTP (e.g. `1 2 3 4 5 6`)", parse_mode="md")

    if step == "add_phone_otp":
        client = s.get("client")
        if not client:
            reset(uid)
            return await e.reply(f"{Emojis.ALERT} Session expired. Try /start")
        try:
            await client.sign_in(phone=s["phone"], code=text.replace(" ", ""),
                                 phone_code_hash=s["phone_code_hash"])
        except PhoneCodeInvalidError:
            return await e.reply(f"{Emojis.ALERT} Invalid code. Try again:")
        except PhoneCodeExpiredError:
            reset(uid)
            return await e.reply(f"{Emojis.ALERT} Code expired. /start")
        except SessionPasswordNeededError:
            s["step"] = "add_phone_password"
            return await e.reply(f"{Emojis.LOCK} 2FA enabled. Send password:")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(f"{Emojis.CONFIRM} Added `{acc['phone']}` — {acc['name']}",
                             buttons=MAIN_MENU, parse_mode="md")

    if step == "add_phone_password":
        client = s.get("client")
        try:
            await client.sign_in(password=text)
        except Exception as ex:
            return await e.reply(f"{Emojis.ALERT} Wrong password: {ex}\nTry again:")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(f"{Emojis.CONFIRM} Added `{acc['phone']}`",
                             buttons=MAIN_MENU, parse_mode="md")

    if step == "add_string_input":
        try:
            acc = await validate_session_string(text, uid)
        except Exception as ex:
            return await e.reply(f"{Emojis.ALERT} {ex}\nSend a valid string:")
        reset(uid)
        return await e.reply(f"{Emojis.CONFIRM} Added `{acc['phone']}` — {acc['name']}",
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
        msg = f"{Emojis.CONFIRM} {added} sessions added."
        if bad:
            msg += f"\n{Emojis.ALERT} {len(bad)} failed:\n" + "\n".join(f"· {b}" for b in bad[:10])
        return await e.reply(msg, buttons=MAIN_MENU, parse_mode="md")

    if step == "remove_input":
        phone = text if text.startswith("+") else "+" + text
        acc = next((a for a in my_accounts(uid) if a["phone"] == phone), None)
        if not acc:
            return await e.reply(f"{Emojis.ALERT} Account not found.")
        c = clients.pop(phone, None)
        if c:
            await c.disconnect()
        accounts.remove(acc)
        save_accounts()
        p = os.path.join(config.SESSIONS_DIR, phone.lstrip("+") + ".session")
        if os.path.exists(p):
            os.remove(p)
        reset(uid)
        return await e.reply(f"{Emojis.CLEAR} Removed `{phone}`",
                             buttons=MAIN_MENU, parse_mode="md")

    if step == "set":
        m = re.fullmatch(r"([\d.]+)\s*-\s*([\d.]+)", text)
        if not m or float(m.group(1)) > float(m.group(2)):
            return await e.reply(f"{Emojis.ALERT} Format: `1-3` (min-max seconds)", parse_mode="md")
        st = get_settings(uid)
        st["delay_min"], st["delay_max"] = float(m.group(1)), float(m.group(2))
        save_settings()
        reset(uid)
        return await e.reply(f"{Emojis.CONFIRM} Delay set: `{st['delay_min']}`–`{st['delay_max']}`s",
                             buttons=MAIN_MENU, parse_mode="md")

    # ── Campaign steps ──
    if step in ("camp_post", "camp_private_invite", "camp_count", "camp_emoji",
                "camp_btn", "camp_target", "camp_dm_text", "sched_time",
                "camp_poll_options", "camp_channel_target", "camp_timer"):
        if not is_admin(uid):
            reset(uid)
            return await e.reply(no_access())
        if "camp_opts" not in s:
            s["camp_opts"] = {}

    # ── Post URL step ──
    if step == "camp_post":
        parsed = parse_post_url(text)
        if not parsed:
            return await e.reply(
                f"{Emojis.ALERT} Invalid post URL.\n\nFormat:\n"
                f"`https://t.me/channel/123` (public)\n"
                f"`https://t.me/c/1234567890/123` (private)",
                parse_mode="md")

        s["camp_opts"]["post_ref"] = parsed[0]
        s["camp_opts"]["msg_id"] = parsed[1]
        s.pop("post_btns", None)
        s.pop("post_poll", None)

        if parsed[0][0] == "c":
            s["step"] = "camp_private_invite"
            return await e.reply(
                f"{Emojis.LOCK} **{fancy('PRIVATE CHANNEL DETECTED')}**\n\n"
                "This post is inside a private channel. Accounts must be members.\n\n"
                "📩 **Send the channel's invite link:**\n"
                "`https://t.me/+AbCdEfGh123`\n\n"
                "➡️ Accounts will **JOIN first, then React/Vote**.\n"
                "💡 If already members, type `skip`.",
                buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]], parse_mode="md")

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
                                preview += f"\n🗳️ **{len(s['post_btns'])} inline buttons found:**"
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
                            preview = "\n\n⚠️ Post not found."
                    except Exception as ex:
                        preview = f"\n\n⚠️ Preview error: {str(ex)[:50]}"
                else:
                    preview = "\n\n⚠️ Could not open the post."

        s["step"] = "camp_count"
        total_accs = len(accs)
        btn_rows.append([Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")])
        return await e.reply(
            f"🔢 **{fancy('HOW MANY ACCOUNTS?')}**\n\nAvailable: **{total_accs}**\n"
            f"`0` = All available{preview}",
            buttons=btn_rows, parse_mode="md")

    # ── Private channel: collect invite link ──
    if step == "camp_private_invite":
        if text.lower() in ("skip", "no", "already"):
            s["step"] = "camp_count"
            total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
            return await e.reply(
                f"🔢 **{fancy('HOW MANY ACCOUNTS?')}**\n\nAvailable: **{total_accs}**\n"
                "`0` = All available\n\n⚠️ Without invite link, only already-members can act.",
                parse_mode="md")

        m = INVITE_RE.search(text)
        if not m:
            return await e.reply(
                f"{Emojis.ALERT} Invalid invite link. Format:\n"
                f"`https://t.me/+AbCdEfGh123`\n\n"
                "Or type `skip` if already members.", parse_mode="md")

        s["camp_opts"]["join_target"] = ("invite", m.group(1))
        s["step"] = "camp_count"
        return await e.reply(
            f"{Emojis.CONFIRM} **{fancy('JOIN + ACT MODE ENABLED')}**\n\n"
            "During the campaign, every account will:\n"
            "1️⃣ Join the private channel\n2️⃣ Wait for sync\n3️⃣ React / Vote\n\n"
            f"🔢 **How many accounts?**\n`0` = All available",
            parse_mode="md")

    if step == "camp_count":
        if not text.isdigit():
            return await e.reply(f"{Emojis.ALERT} Send a number (e.g. `50`). `0` means all available.",
                                 parse_mode="md")
        s["camp_opts"]["count"] = int(text)

        action = s["camp_action"]

        if action in TIMER_ACTIONS:
            s["step"] = "camp_timer"
            return await e.reply(
                f"{Emojis.TIMER} **{fancy('SET TIMER')}**\n\n"
                "**NEW:** Customize batch size & gap!\n\n"
                "Formats:\n"
                "`30`       → 1 account, 30s gap\n"
                "`1m`       → 1 account, 1 min gap\n"
                "`2 1m`     → 2 accounts together, then 1 min gap\n"
                "`5 30s`    → 5 accounts together, then 30s gap\n"
                "`0`        → No timer (all at once)\n\n"
                "💡 `2 1m` with 50 accounts = 2 reqs per minute!",
                buttons=[[Button.inline(f"{Emojis.CLOCK} No Timer", b"timer_off")],
                         [Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]], parse_mode="md")
        return await camp_next(e, uid)

    if step == "camp_timer":
        t = parse_timer(text)
        if t is None:
            return await e.reply(
                f"{Emojis.ALERT} Invalid timer. Use:\n"
                "`30` `1m` `2 1m` `5 30s` `0` for none.",
                parse_mode="md")
        s["camp_opts"]["timer"] = t
        return await camp_next(e, uid)

    if step == "camp_emoji":
        if not text.strip():
            return await e.reply(f"{Emojis.ALERT} Send an emoji!")
        s["camp_opts"]["emoji"] = text.strip()
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            if s["camp_opts"].get("btn_index") or s["camp_opts"].get("btn_text"):
                return await ask_run(e, uid)
            s["step"] = "camp_btn"
            return await e.reply(f"{Emojis.VOTE} Button number/text: `1` / `Vote Now`", parse_mode="md")
        return await ask_run(e, uid)

    if step == "camp_btn":
        if text.isdigit():
            s["camp_opts"]["btn_index"] = int(text)
            s["camp_opts"]["btn_text"] = None
        else:
            s["camp_opts"]["btn_index"] = None
            s["camp_opts"]["btn_text"] = text
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            s["step"] = "camp_emoji"
            return await e.reply(f"{Emojis.STAR} Now send reaction emoji:\nExample: `❤️`", parse_mode="md")
        return await ask_run(e, uid)

    if step == "camp_poll_options":
        options = [x.strip() for x in text.split(',') if x.strip().isdigit()]
        if not options:
            return await e.reply(f"{Emojis.ALERT} Invalid. Use: `0,1,2`", parse_mode="md")
        s["camp_opts"]["poll_options"] = [int(x) for x in options]
        return await ask_run(e, uid)

    if step == "camp_target":
        parsed = parse_join_target(text)
        if not parsed:
            return await e.reply(
                f"{Emojis.ALERT} Invalid target.\n\nFormat:\n"
                f"`@channel`\n`https://t.me/+invite_hash`\n`-1001234567890`",
                parse_mode="md")
        s["camp_opts"]["target"] = parsed
        if s["camp_action"] == "dm":
            s["step"] = "camp_dm_text"
            return await e.reply(f"{Emojis.REQUEST} **Send the DM message:**", parse_mode="md")
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
            return await e.reply(f"{Emojis.ALERT} Format: `30m`, `2h`, `1d`", parse_mode="md")
        mult = {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
        s["sched_delay"] = int(m.group(1)) * mult
        label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
        return await e.reply(f"📅 **{label}** in **{text}**. Confirm?",
                             buttons=[[styled_btn(f"{Emojis.CONFIRM} Confirm", b"do_schedule", "success")],
                                      [Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])

async def camp_next(e, uid):
    s = state(uid)
    action = s["camp_action"]

    if action in ("join", "join_request", "leave"):
        if "target" not in s["camp_opts"]:
            s["step"] = "camp_target"
            return await e.reply(
                f"📌 **Send channel target:**\n\n"
                f"Username: `@channel`\nInvite: `https://t.me/+hash`\nID: `-100123`",
                parse_mode="md")
        return await ask_run(e, uid)

    if action == "dm":
        if "target" not in s["camp_opts"]:
            s["step"] = "camp_target"
            return await e.reply(f"{Emojis.REQUEST} **Send username or user ID:**\n\n`@username` or `123456789`",
                                 parse_mode="md")
        if "dm_text" not in s["camp_opts"]:
            s["step"] = "camp_dm_text"
            return await e.reply(f"{Emojis.REQUEST} **Send the DM message:**", parse_mode="md")
        return await ask_run(e, uid)

    if action in ("react", "react_vote", "react_vote_view"):
        s["step"] = None
        return await e.reply(
            f"{Emojis.STAR} **{fancy('REACTION TYPE')}**",
            buttons=[[styled_btn("🎯 Specific Emoji", b"react_specific", "primary")],
                     [styled_btn("🎲 Random Emoji", b"react_random", "success")],
                     [Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])

    if action in ("vote", "unvote"):
        if s["camp_opts"].get("btn_index") or s["camp_opts"].get("btn_text"):
            return await ask_run(e, uid)
        s["step"] = "camp_btn"
        return await e.reply(
            f"{Emojis.VOTE} Send button **number** or **text**:\n`1` / `Vote Now`\n\n"
            "💡 (If buttons were shown above, just click one.)", parse_mode="md")

    if action == "poll_vote":
        s["step"] = "camp_poll_options"
        return await e.reply(
            f"{Emojis.CHART} Send poll option numbers (comma separated):\n`0,1,2`",
            parse_mode="md")

    return await ask_run(e, uid)

async def ask_run(e, uid):
    s = state(uid)
    s["step"] = None
    label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
    opts = s.get("camp_opts", {})

    summary = f"{Emojis.NEXT} **{fancy('CAMPAIGN READY')}**\n\nAction: **{label}**\n"
    if "post_ref" in opts:
        summary += f"Post ID: `{opts['msg_id']}`\n"
    if "join_target" in opts:
        summary += f"🔐 Auto-Join: `YES`\n"
    if "count" in opts:
        count = opts['count']
        total_accs = len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))
        if count == 0:
            summary += f"Accounts: **All ({total_accs})**\n"
        else:
            summary += f"Accounts: **{min(count, total_accs)}**\n"
    if "timer" in opts:
        timer = opts['timer']
        if timer[1] > 0:
            summary += f"{Emojis.TIMER} Timer: **{fmt_timer(timer)}**\n"
        else:
            summary += f"{Emojis.TIMER} Timer: **None (instant)**\n"
    if "emoji" in opts:
        emoji_display = "🎲 Random" if opts['emoji'].lower() in ("random","rand","r","🍀") else opts['emoji']
        summary += f"Emoji: {emoji_display}\n"
    if opts.get("btn_index") or opts.get("btn_text"):
        summary += f"Button: `{opts.get('btn_index') or opts.get('btn_text')}`\n"
    if "target" in opts:
        summary += f"Target: `{opts['target'][1]}`\n"
    if "dm_text" in opts:
        summary += f"Message: {opts['dm_text'][:60]}\n"
    if "poll_options" in opts:
        summary += f"Poll Options: {opts['poll_options']}\n"

    summary += f"\n📊 Available: **{len(get_admin_accounts(uid) if is_admin(uid) else my_accounts(uid))}**"

    await e.reply(summary, parse_mode="md")
    await e.reply("▶️ **Run now or schedule?**",
               buttons=[[styled_btn("▶️ Run Now", b"run_now", "success"),
                         styled_btn("📅 Schedule", b"schedule_btn", "primary")],
                        [Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])

@bot.on(events.CallbackQuery(pattern=b"^schedule_btn$"))
async def sched_btn(e):
    if not is_admin(e.sender_id):
        return await e.answer(no_access(), alert=True)
    s = state(e.sender_id)
    s["step"] = "sched_time"
    await e.edit("📅 **Schedule Time**\n\nSend delay: `30m` / `2h` / `1d`",
                 buttons=[[Button.inline(f"{Emojis.CANCEL} Cancel", b"menu")]])

# .txt file upload handler
@bot.on(events.NewMessage(func=lambda e: e.document))
async def txt_upload(e):
    s = state(e.sender_id)
    if s.get("step") != "bulk_input":
        return
    fname = (e.document.attributes[0].file_name if e.document.attributes else "") or ""
    if not fname.endswith(".txt"):
        return await e.reply(f"{Emojis.ALERT} Only `.txt` files.")
    data = await e.download_media(file=bytes)
    e.text = data.decode("utf-8", errors="ignore")
    await steps(e)

# ==========================================================
#  SCHEDULER LOOP
# ==========================================================

async def scheduler_loop(bot_client):
    while True:
        try:
            now = time.time()
            to_run = [s for s in scheduled if s["due_at"] <= now]
            for sched_item in to_run:
                scheduled.remove(sched_item)
                owner = sched_item["owner"]
                opts = sched_item["opts"]
                asyncio.create_task(run_campaign(owner, opts))
            if to_run:
                save_scheduled()
            await asyncio.sleep(5)
        except Exception as ex:
            print(f"[scheduler] error: {ex}")
            await asyncio.sleep(10)

# ==========================================================
#  MAIN
# ==========================================================

async def main():
    load_scheduled()
    print(f"[VoteFlow] Restoring ALL {len(accounts)} accounts from {config.ACCOUNTS_FILE} ...")
    restored, failed = 0, 0
    for acc in accounts:
        try:
            c = await get_client(acc)
            if c:
                restored += 1
                print(f"[restore] ✅ {acc.get('phone', 'unknown')}")
            else:
                failed += 1
                print(f"[restore] ❌ {acc.get('phone', 'unknown')} — dead/expired")
        except Exception as ex:
            failed += 1
            print(f"[restore] ❌ {acc.get('phone', 'unknown')}: {str(ex)[:60]}")
        await asyncio.sleep(0.3)

    print(f"[VoteFlow] Restored: {restored}/{len(accounts)} (failed: {failed})")
    asyncio.create_task(scheduler_loop(bot))
    print(f"[VoteFlow] Telethon version: {__import__('telethon').__version__}")
    print(f"[VoteFlow] Running. Accounts: {len(accounts)}, Admins: {len(admins)+1}, Scheduled: {len(scheduled)}")
    print(f"[VoteFlow] Button colors supported: {HAS_BTN_STYLE}")
    print(f"[VoteFlow] Loaded OWNER_IDS: {config.OWNER_IDS}")
    print(f"[VoteFlow] Support bot: @{CREDIT_BOT}")
    print(f"[VoteFlow] Admin Limits active: {sum(1 for a in admins if a.get('limit', 0) > 0)}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    bot.loop.run_until_complete(main())
