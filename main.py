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
from telethon.tl.functions.messages import ImportChatInviteRequest, SendVoteRequest
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import PeerChannel, ReactionEmoji

import config

os.makedirs(config.SESSIONS_DIR, exist_ok=True)
LOCK = threading.Lock()

# ══════════════════════════════════════════════════════════
#  STORAGE
# ══════════════════════════════════════════════════════════

def jload(path, default):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(default, f)
    with LOCK:
        with open(path) as f:
            return json.load(f)

def jsave(path, data):
    with LOCK:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

accounts  = jload(config.ACCOUNTS_FILE, [])
admins    = jload(config.ADMINS_FILE, [])
settings  = jload(config.SETTINGS_FILE, {})
campaigns = jload(config.CAMPAIGNS_FILE, [])

def save_accounts():  jsave(config.ACCOUNTS_FILE, accounts)
def save_admins():    jsave(config.ADMINS_FILE, admins)
def save_settings():  jsave(config.SETTINGS_FILE, settings)
def save_campaigns(): jsave(config.CAMPAIGNS_FILE, campaigns)

# ─── Scheduled campaigns persistence ───
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
        with open(config.SCHEDULED_FILE, "w") as f:
            json.dump(scheduled, f)
    except Exception as ex:
        print(f"[scheduled] save error: {ex}")

# ══════════════════════════════════════════════════════════
#  ACCESS CONTROL
# ══════════════════════════════════════════════════════════

def is_owner(uid):
    return uid == config.OWNER_ID

def is_admin(uid):
    return is_owner(uid) or uid in admins

def my_accounts(uid):
    return [a for a in accounts if a.get("owner") == uid]

user_state = {}
clients = {}

def state(uid):
    return user_state.setdefault(uid, {})

def reset(uid):
    user_state.pop(uid, None)

def get_settings(uid):
    return settings.setdefault(str(uid), {"delay_min": 1.0, "delay_max": 2.5})

# ══════════════════════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════════════════════

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
        raise ValueError("session expired / not authorized")
    return await save_session_account(c, owner)

async def check_status(uid):
    total, active, expired = len(my_accounts(uid)), 0, 0
    for a in my_accounts(uid):
        c = await get_client(a)
        if c is None:
            expired += 1
        else:
            try:
                await c.get_me()
                active += 1
            except Exception:
                expired += 1
    return total, active, expired

# ══════════════════════════════════════════════════════════
#  PARSING
# ══════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════
#  CAMPAIGN WORKERS (FIXED - WORKS WITH ALL VERSIONS)
# ══════════════════════════════════════════════════════════

async def do_react(c, ent, msg_id, emoji):
    """Send reaction - works with all Telethon versions"""
    msg = await c.get_messages(ent, ids=msg_id)
    
    # Try different methods in order
    try:
        # Method 1: Latest Telethon
        await c.send_reaction(ent, msg, reaction=ReactionEmoji(emoticon=emoji))
        return
    except (AttributeError, TypeError):
        pass
    
    try:
        # Method 2: Older Telethon (1.28+)
        await c.react(msg, reaction=emoji)
        return
    except (AttributeError, TypeError):
        pass
    
    try:
        # Method 3: Another older method
        await c.send_reaction(ent, msg, reaction=emoji)
        return
    except (AttributeError, TypeError):
        pass
    
    try:
        # Method 4: Mark as read (last resort)
        await c.send_read_acknowledge(ent, msg)
        return
    except Exception as e:
        raise ValueError(f"Reaction failed: {str(e)[:30]}")

async def do_vote(c, ent, msg_id, btn_index, btn_text):
    """Vote on inline button"""
    msg = await c.get_messages(ent, ids=msg_id)
    if not msg.buttons:
        raise ValueError("no inline buttons on message")
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
    await btn.click()

async def do_poll_vote(c, ent, msg_id, poll_option_ids):
    """Vote on a poll message"""
    try:
        msg = await c.get_messages(ent, ids=msg_id)
        if not msg.poll:
            raise ValueError("This message is not a poll")
        
        # Send vote
        await c(SendVoteRequest(
            peer=ent,
            msg_id=msg_id,
            options=poll_option_ids
        ))
        return True
    except Exception as e:
        raise ValueError(f"Poll vote failed: {str(e)[:50]}")

async def do_view(c, ent, msg_id):
    msg = await c.get_messages(ent, ids=msg_id)
    await c.send_read_acknowledge(ent, msg)

async def do_join(c, target):
    kind, val = target
    try:
        if kind == "username":
            await c(JoinChannelRequest(val))
        elif kind == "id":
            await c(JoinChannelRequest(await resolve_entity(c, target)))
        elif kind == "invite":
            await c(ImportChatInviteRequest(val))
    except UserAlreadyParticipantError:
        pass

async def do_leave(c, target):
    if target[0] == "invite":
        raise ValueError("invite link se leave nahi hota — @username ya chat id do")
    await c(LeaveChannelRequest(await resolve_entity(c, target)))

async def do_dm(c, target, text):
    if target[0] == "invite":
        raise ValueError("DM target @username ya user id hona chahiye")
    ent = await resolve_entity(c, target) if target[0] == "username" else await c.get_entity(target[1])
    await c.send_message(ent, text)

async def run_campaign(uid, action, opts):
    accs = my_accounts(uid)
    if not accs:
        return 0, ["aapke paas koi account add nahi hai"]
    random.shuffle(accs)
    st = get_settings(uid)
    ok, fail = 0, []
    
    for acc in accs:
        try:
            c = await get_client(acc)
            if c is None:
                fail.append(f"{acc['phone']}: session expired")
                continue
                
            post_ref, msg_id = opts.get("post_ref"), opts.get("msg_id")
            target, emoji = opts.get("target"), opts.get("emoji")
            bi, bt = opts.get("btn_index"), opts.get("btn_text")
            poll_options = opts.get("poll_options", [])

            if action in ("react", "react_vote", "react_vote_view"):
                ent = await resolve_entity(c, post_ref)
                if action == "react_vote_view":
                    await do_view(c, ent, msg_id)
                    await asyncio.sleep(random.uniform(1, 2))
                await do_react(c, ent, msg_id, emoji)
                if action != "react":
                    await asyncio.sleep(random.uniform(1, 2))
                    await do_vote(c, ent, msg_id, bi, bt)
                    
            elif action == "vote":
                await do_vote(c, await resolve_entity(c, post_ref), msg_id, bi, bt)
                
            elif action == "poll_vote":
                ent = await resolve_entity(c, post_ref)
                if isinstance(poll_options, str):
                    poll_options = [int(x.strip()) for x in poll_options.split(',') if x.strip().isdigit()]
                await do_poll_vote(c, ent, msg_id, poll_options)
                
            elif action == "view":
                await do_view(c, await resolve_entity(c, post_ref), msg_id)
                
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
            fail.append(f"{acc['phone']}: flood wait {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 30))
        except Exception as e:
            error_msg = str(e)[:50]
            fail.append(f"{acc['phone']}: {type(e).__name__}: {error_msg}")
            
        await asyncio.sleep(random.uniform(st["delay_min"], st["delay_max"]))

    campaigns.append({"owner": uid, "action": action, "ok": ok, "fail": len(fail),
                      "time": time.strftime("%d-%m %H:%M")})
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
                txt = (f"⏰ **Scheduled campaign finished**\nAction: `{s['action']}`\n"
                       f"✅ {ok}  ❌ {len(fail)}")
                if fail:
                    txt += "\n" + "\n".join(f"· {f}" for f in fail[:10])
                await bot.send_message(s["owner"], txt, parse_mode="md")
            except Exception as e:
                print(f"[scheduler] {e}")
        await asyncio.sleep(5)

# ══════════════════════════════════════════════════════════
#  BOT
# ══════════════════════════════════════════════════════════

bot = TelegramClient(os.path.join(config.SESSIONS_DIR, "control_bot"),
                     config.API_ID, config.API_HASH).start(bot_token=config.BOT_TOKEN)

ACTIONS = [
    ("react", "😀 React (Specific Emoji)"),
    ("vote", "🗳 Vote (Inline Button)"),
    ("poll_vote", "📊 Poll Vote"),
    ("react_vote", "😀+🗳 React + Vote"),
    ("view", "👁 View"),
    ("react_vote_view", "👁 React + Vote + View"),
    ("join", "➕ Join Channel/GC"),
    ("join_request", "📨 Join Request (Private)"),
    ("leave", "🚪 Leave Channel/GC"),
    ("dm", "📩 Bulk DM"),
]

MAIN_MENU = [
    [Button.inline("👤 My Account", b"myacc"), Button.inline("➕ Add Account", b"add")],
    [Button.inline("🚀 New Campaign", b"camp"), Button.inline("📋 My Campaigns", b"mycamp")],
    [Button.inline("📅 Schedule", b"sched_info"), Button.inline("📊 My Status", b"mystat")],
    [Button.inline("⚙️ Settings", b"set"), Button.inline("🧑‍💼 My Profile", b"profile")],
    [Button.inline("🚪 Leave Channel/GC", b"leave_menu"), Button.inline("❓ Help & Guide", b"help")],
]

def menu_text(uid):
    return (f"🤖 **VoteFlow Panel**\n\n"
            f"Aapke Accounts: **{len(my_accounts(uid))}**\n"
            f"Access: **{'Owner 👑' if is_owner(uid) else ('Admin ✅' if is_admin(uid) else 'User (add only)')}**\n\n"
            f"Menu choose karo:")

def no_access():
    return ("⛔ **Access denied!**\n\nCampaigns (Vote/React/View/Join/DM) sirf "
            "**Owner aur Admins** chala sakte hain.\n"
            "Owner se access mangoo: `/addadmin`")

# ── Commands ──────────────────────────────────────────────

@bot.on(events.NewMessage(pattern="^/(start|menu|help)$"))
async def cmd_start(e):
    reset(e.sender_id)
    await e.reply(menu_text(e.sender_id), buttons=MAIN_MENU, parse_mode="md")

@bot.on(events.NewMessage(pattern="^/me$"))
async def cmd_me(e):
    total, active, expired = await check_status(e.sender_id)
    await e.reply(f"👤 Accounts: {total} | 🟢 Active: {active} | 🔴 Expired: {expired}")

@bot.on(events.NewMessage(pattern="^/addadmin(@\w+)?(\s+.*)?$"))
async def cmd_addadmin(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Ye command sirf **Owner** chala sakta hai.", parse_mode="md")
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
                return await e.reply("❌ User nahi mila.")
    if target_id is None:
        return await e.reply("Usage: `/addadmin <user_id>` ya user ke message pe reply karke `/addadmin`",
                             parse_mode="md")
    if is_admin(target_id):
        return await e.reply(f"ℹ️ `{target_id}` pehle se admin hai.")
    admins.append(target_id)
    save_admins()
    await e.reply(f"✅ **`{target_id}` ko admin access de diya!**\nAb vo campaigns chala sakta hai.",
                  parse_mode="md")
    try:
        await bot.send_message(target_id, "🎉 Aapko **VoteFlow bot** pe Admin access mil gaya!\n"
                                          "Ab aap campaigns run kar sakte ho. /start")
    except Exception:
        pass

@bot.on(events.NewMessage(pattern="^/rmadmin(\s+.*)?$"))
async def cmd_rmadmin(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Ye command sirf **Owner** chala sakta hai.", parse_mode="md")
    target_id = None
    if e.reply_to_msg_id:
        msg = await e.get_reply_message()
        target_id = msg.sender_id
    elif e.pattern_match.group(1) and e.pattern_match.group(1).strip().isdigit():
        target_id = int(e.pattern_match.group(1).strip())
    if target_id is None:
        return await e.reply("Usage: `/rmadmin <user_id>` ya reply karke `/rmadmin`")
    if target_id not in admins:
        return await e.reply("ℹ️ Ye admin list me nahi hai.")
    admins.remove(target_id)
    save_admins()
    await e.reply(f"🗑 `{target_id}` ka admin access **revoke** kar diya.", parse_mode="md")

@bot.on(events.NewMessage(pattern="^/adminlist$"))
async def cmd_adminlist(e):
    if not is_owner(e.sender_id):
        return await e.reply("⛔ Ye command sirf **Owner** chala sakta hai.", parse_mode="md")
    if not admins:
        return await e.reply("Koi admins nahi hain. Add karo: `/addadmin <id>`", parse_mode="md")
    lines = ["👮 **Admins:**\n"]
    for a in admins:
        try:
            u = await bot.get_entity(a)
            lines.append(f"· `{a}` — {u.first_name}")
        except Exception:
            lines.append(f"· `{a}` — (unknown)")
    await e.reply("\n".join(lines), parse_mode="md")

# ── Callback router ───────────────────────────────────────

@bot.on(events.CallbackQuery())
async def cb(e):
    uid = e.sender_id
    data = e.data.decode()
    s = state(uid)

    if data == "menu":
        reset(uid)
        return await e.edit(menu_text(uid), buttons=MAIN_MENU, parse_mode="md")

    # ── Owner-only ──
    if data == "owner_panel":
        if not is_owner(uid):
            return await e.answer("⛔ Sirf Owner!", alert=True)
        lines = [f"👑 **Owner Panel**\n\nAdmins ({len(admins)}):"]
        lines += [f"· `{a}`" for a in admins] or ["· (koi nahi)"]
        lines.append(f"\nTotal accounts (sab users): **{len(accounts)}**")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    # ── My Account / Profile / Status ──
    if data == "myacc" or data == "profile":
        total, active, expired = await check_status(uid)
        accs = my_accounts(uid)
        lines = [f"🧑‍💼 **My Profile**\n",
                 f"ID: `{uid}`",
                 f"Access: **{'Owner 👑' if is_owner(uid) else ('Admin ✅' if is_admin(uid) else 'User')}**\n",
                 f"👤 **My Accounts**: {total}",
                 f"🟢 Active: {active}",
                 f"🔴 Expired/Dead: {expired}"]
        for a in accs[:15]:
            alive = "🟢" if a["phone"] in clients and clients[a["phone"]].is_connected() else "🔴"
            lines.append(f"{alive} `{a['phone']}` — {a.get('name','?')}")
        if len(accs) > 15:
            lines.append(f"…+{len(accs)-15} more")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    if data == "mystat":
        total, active, expired = await check_status(uid)
        myc = [c for c in campaigns if c["owner"] == uid]
        lines = [f"📊 **My Status**\n",
                 f"Accounts: {total} | Active: {active} | Expired: {expired}",
                 f"Campaigns run: {len(myc)}",
                 f"Scheduled: {len([x for x in scheduled if x['owner']==uid])}"]
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
            return await e.edit("📋 Aapne abhi koi campaign run nahi kiya.",
                                buttons=[[Button.inline("« Back", b"menu")]])
        lines = [f"📋 **My Campaigns ({len(myc)})**\n"]
        for c in myc[-15:]:
            lines.append(f"· `{c['time']}` {c['action']} → ✅{c['ok']} ❌{c['fail']}")
        return await e.edit("\n".join(lines), parse_mode="md",
                            buttons=[[Button.inline("« Back", b"menu")]])

    # ── Help ──
    if data == "help":
        return await e.edit(
            "❓ **Help & Guide**\n\n"
            "**1. Account Add karo** — Phone+OTP ya Session String, ya Bulk (.txt)\n"
            "**2. Access** — Campaigns sirf Owner/Admins chala sakte hain.\n"
            "Owner `/addadmin <id>` se access deta hai.\n"
            "**3. New Campaign** — Action chuno → Post URL ya target do → Run/Schedule\n\n"
            "**Post URLs:**\n`https://t.me/channel/123`\n`https://t.me/c/1234567890/123`\n\n"
            "**Actions:**\n"
            "• React — Specific emoji reaction (👍❤🔥🎉)\n"
            "• Vote — Inline button click\n"
            "• Poll Vote — Telegram poll vote\n"
            "• React+Vote — Both reaction and vote\n"
            "• View — Just view the message\n"
            "• Join — Join channel/group\n"
            "• Leave — Leave channel/group\n"
            "• DM — Bulk direct message\n\n"
            "**Commands:**\n"
            "`/start` `/menu` — panel\n`/help` — ye guide\n`/me` — quick stats\n\n"
            "**Owner only:**\n`/addadmin <id>` — access do\n`/rmadmin <id>` — access lo\n"
            "`/adminlist` — admins dekho",
            parse_mode="md", buttons=[[Button.inline("« Back", b"menu")]])

    # ── Add Account ──
    if data == "add":
        s.clear()
        s["step"] = "add_choice"
        return await e.edit("➕ **Add Account**\n\nKaise add karna hai?",
                            buttons=[[Button.inline("📱 Phone + OTP", b"add_phone")],
                                     [Button.inline("🔑 Session String", b"add_string")],
                                     [Button.inline("📋 Bulk Sessions", b"bulk")],
                                     [Button.inline("« Back", b"menu")]], parse_mode="md")

    if data == "add_phone":
        s.clear()
        s["step"] = "add_phone_number"
        return await e.edit("📱 Phone number bhejo (international format):\n`+919876543210`",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "add_string":
        s.clear()
        s["step"] = "add_string_input"
        return await e.edit("🔑 Session string bhejo (ek).", 
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    if data == "bulk":
        s.clear()
        s["step"] = "bulk_input"
        return await e.edit("📋 **Bulk Sessions**\n\nEk message me kai strings paste karo "
                            "(1 per line) **ya** `.txt` file upload karo (1 string per line).",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    # ── Remove ──
    if data == "remove_acc":
        s.clear()
        s["step"] = "remove_input"
        return await e.edit("🗑 Remove karne ke liye phone number bhejo:\n`+919876543210`",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    # ── Settings ──
    if data == "set":
        st = get_settings(uid)
        return await e.edit(f"⚙️ **Settings**\n\nDelay between accounts: "
                            f"`{st['delay_min']}`–`{st['delay_max']}` sec\n\n"
                            "Naya delay set karo (format: `min-max` seconds, e.g. `1-3`):",
                            buttons=[[Button.inline("« Back", b"menu")]], parse_mode="md")

    # ── Schedule info ──
    if data == "sched_info":
        return await e.edit("📅 **Schedule**\n\nCampaign banate waqt 'Run Now' ki jagah "
                            "'📅 Schedule' dabao, phir delay bhejo: `30m` / `2h` / `1d`.\n"
                            "Bot us waqt khud campaign chala dega aur result bhejega.",
                            buttons=[[Button.inline("« Back", b"menu")]], parse_mode="md")

    # ── Campaign (ADMIN-ONLY) ──
    if data == "camp":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s.clear()
        s["step"] = "camp_action"
        btns = [[Button.inline(label, f"act:{key}".encode())] for key, label in ACTIONS]
        btns.append([Button.inline("« Back", b"menu")])
        return await e.edit("🚀 **New Campaign**\n\nAction chuno:", buttons=btns, parse_mode="md")

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
            return await e.edit("📊 Poll message URL bhejo:\n`https://t.me/channel/123`",
                                buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")
        
        if key in ("join", "join_request", "leave", "dm"):
            s["step"] = "camp_target"
            hint = {
                "join": "➕ Join karne ke liye bhejo:\n`@channelname` ya `https://t.me/+AbCd...` (private) ya chat id",
                "join_request": "📨 Join Request ke liye bhejo (public ya private dono):\n`@channelname` ya `https://t.me/+AbCd...` ya chat id",
                "leave": "🚪 Leave karne ke liye bhejo:\n`@channelname` ya chat id",
                "dm": "📩 DM target bhejo:\n`@username` ya user id",
            }[key]
            return await e.edit(hint, buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")
        
        s["step"] = "camp_post"
        return await e.edit("🔗 Post URL bhejo:\n`https://t.me/channel/123`\n"
                            "`https://t.me/c/1234567890/123` (private)",
                            buttons=[[Button.inline("« Cancel", b"menu")]], parse_mode="md")

    # ── Leave via my chats ──
    if data == "leave_menu":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s.clear()
        s["step"] = "camp_target"
        s["camp_action"] = "leave"
        return await e.edit(
            "🚪 **Leave Channel/GC**\n\nOption chuno:\n"
            "· @username / chat id type karo, **ya**\n"
            "· Neeche apni chats se select karo",
            buttons=[[Button.inline("📂 Meri Chats Dikho", b"list_chats")],
                     [Button.inline("✍️ Manually Bhejo", b"leave_manual")],
                     [Button.inline("« Cancel", b"menu")]])

    if data == "leave_manual":
        state(uid)["step"] = "camp_target"
        return await e.edit("🚪 @username ya chat id bhejo (leave ke liye):",
                            buttons=[[Button.inline("« Cancel", b"menu")]])

    if data == "list_chats":
        accs = my_accounts(uid)
        if not accs:
            return await e.edit("❌ Pehle account add karo.", buttons=[[Button.inline("« Back", b"menu")]])
        c = await get_client(accs[0])
        if not c:
            return await e.edit("❌ Pehla account dead hai.", buttons=[[Button.inline("« Back", b"menu")]])
        dialogs = await c.get_dialogs(limit=25)
        btns = []
        for d in dialogs:
            if d.is_group or d.is_channel:
                btns.append([Button.inline(f"🚪 {d.name[:30]}", f"doleave:{d.id}".encode())])
        btns.append([Button.inline("« Cancel", b"menu")])
        return await e.edit("📂 Pehle account ki chats — click karke leave karo:", buttons=btns)

    if data.startswith("doleave:"):
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        chat_id = int(data[8:])
        ok, fail = await run_campaign(uid, "leave", {"target": ("id", chat_id)})
        await e.answer(f"✅ {ok} leave ho gaye, ❌ {len(fail)} fail" if ok else
                       f"❌ Fail: {fail[0][:80] if fail else 'unknown'}", alert=True)
        return

    # ── Run / Schedule ──
    if data == "run_now":
        if not is_admin(uid):
            await e.answer(no_access(), alert=True)
            return
        s = state(uid)
        await e.edit("⏳ Campaign chal raha hai saare accounts pe…")
        ok, fail = await run_campaign(uid, s["camp_action"], s["camp_opts"])
        lines = [f"✅ **Done** — {ok} success, {len(fail)} fail"]
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
        return await e.edit("📅 Scheduled! Run hote hi result bhej dunga.",
                            buttons=[[Button.inline("« Menu", b"menu")]])

# ── Text step handler ─────────────────────────────────────

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

    # Phone + OTP flow
    if step == "add_phone_number":
        if not re.fullmatch(r"\+\d{6,15}", text):
            return await e.reply("❌ Format galat. Example: `+919876543210`", parse_mode="md")
        s["phone"] = text
        client = TelegramClient(os.path.join(config.SESSIONS_DIR, text.lstrip("+")),
                                config.API_ID, config.API_HASH)
        await client.connect()
        sent = await client.send_code_request(text)
        s["phone_code_hash"] = sent.phone_code_hash
        s["client"] = client
        s["step"] = "add_phone_otp"
        return await e.reply("🔢 Code bheja gaya! OTP bhejo (e.g. `1 2 3 4 5 6`).")

    if step == "add_phone_otp":
        client = s.get("client")
        if not client:
            reset(uid)
            return await e.reply("Session expire. /start se dobara try karo.")
        try:
            await client.sign_in(phone=s["phone"], code=text.replace(" ", ""),
                                 phone_code_hash=s["phone_code_hash"])
        except PhoneCodeInvalidError:
            return await e.reply("❌ Code galat. Dobara bhejo:")
        except PhoneCodeExpiredError:
            reset(uid)
            return await e.reply("❌ Code expire. /start")
        except SessionPasswordNeededError:
            s["step"] = "add_phone_password"
            return await e.reply("🔒 2FA on hai. Cloud password bhejo:")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(f"✅ Added `{acc['phone']}` — {acc['name']}",
                             buttons=MAIN_MENU, parse_mode="md")

    if step == "add_phone_password":
        client = s.get("client")
        try:
            await client.sign_in(password=text)
        except Exception as ex:
            return await e.reply(f"❌ Password galat: {ex}\nDobara bhejo:")
        acc = await save_session_account(client, uid)
        reset(uid)
        return await e.reply(f"✅ Added `{acc['phone']}`", buttons=MAIN_MENU, parse_mode="md")

    # Session string
    if step == "add_string_input":
        try:
            acc = await validate_session_string(text, uid)
        except Exception as ex:
            return await e.reply(f"❌ {ex}\nValid string bhejo:")
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

    if step == "remove_input":
        phone = text if text.startswith("+") else "+" + text
        acc = next((a for a in my_accounts(uid) if a["phone"] == phone), None)
        if not acc:
            return await e.reply("❌ Ye account aapka nahi mila.")
        c = clients.pop(phone, None)
        if c:
            await c.disconnect()
        accounts.remove(acc)
        save_accounts()
        p = os.path.join(config.SESSIONS_DIR, phone.lstrip("+") + ".session")
        if os.path.exists(p):
            os.remove(p)
        reset(uid)
        return await e.reply(f"🗑 Removed `{phone}`", buttons=MAIN_MENU, parse_mode="md")

    if step == "set":
        m = re.fullmatch(r"([\d.]+)\s*-\s*([\d.]+)", text)
        if not m or float(m.group(1)) > float(m.group(2)):
            return await e.reply("❌ Format: `1-3` (min-max seconds)")
        st = get_settings(uid)
        st["delay_min"], st["delay_max"] = float(m.group(1)), float(m.group(2))
        save_settings()
        reset(uid)
        return await e.reply(f"✅ Delay set: `{st['delay_min']}`–`{st['delay_max']}`s",
                             buttons=MAIN_MENU, parse_mode="md")

    # ── Campaign steps (ADMIN-ONLY) ──
    if step in ("camp_post", "camp_emoji", "camp_btn", "camp_target", "camp_dm_text", "sched_time", "camp_poll_options"):
        if not is_admin(uid):
            reset(uid)
            return await e.reply(no_access())

    if step == "camp_post":
        parsed = parse_post_url(text)
        if not parsed:
            return await e.reply("❌ Invalid URL.\n`https://t.me/channel/123` ya "
                                 "`https://t.me/c/1234567890/123`", parse_mode="md")
        
        # Check if it's poll vote
        if s.get("poll_vote_mode"):
            s["camp_opts"] = {"post_ref": parsed[0], "msg_id": parsed[1]}
            s["step"] = "camp_poll_options"
            return await e.reply("📊 Poll options bhejo (comma separated):\n"
                                 "Example: `0,1,2` (first 3 options)\n"
                                 "Ya sirf ek option: `0`",
                                 parse_mode="md")
        
        s["camp_opts"] = {"post_ref": parsed[0], "msg_id": parsed[1]}
        action = s["camp_action"]
        if action in ("react", "react_vote", "react_vote_view"):
            s["step"] = "camp_emoji"
            return await e.reply("😀 Reaction emoji bhejo: `👍` `❤` `🔥` `🎉` `👏` `😍` `💯`\n"
                                 "Ya koi bhi emoji jo telegram support kare.",
                                 parse_mode="md")
        if action == "vote":
            s["step"] = "camp_btn"
            return await e.reply("🗳 Button bhejo — **number** (1 se) ya button ka **text**:")
        return await ask_run(e, uid)

    if step == "camp_emoji":
        # Validate emoji
        if not text.strip():
            return await e.reply("❌ Kuch emoji toh bhejo!")
        s["camp_opts"]["emoji"] = text.strip()
        if s["camp_action"] in ("react_vote", "react_vote_view"):
            s["step"] = "camp_btn"
            return await e.reply("🗳 Ab button bhejo (number ya text):")
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
            return await e.reply("❌ Invalid options. Use numbers like: `0,1,2`", parse_mode="md")
        s["camp_opts"]["poll_options"] = [int(x) for x in options]
        return await ask_run(e, uid)

    if step == "camp_target":
        parsed = parse_target(text)
        if not parsed:
            return await e.reply("❌ Invalid target. `@username`, `t.me/+hash` invite link, ya chat id do.")
        s["camp_opts"] = {"target": parsed}
        if s["camp_action"] == "dm":
            s["step"] = "camp_dm_text"
            return await e.reply("✉️ DM ka text bhejo:")
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
        s["step"] = "confirm_sched"
        label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
        return await e.reply(f"📅 **{label}** campaign **{text}** baad chalega. Confirm?",
                             parse_mode="md",
                             buttons=[[Button.inline("✅ Confirm", b"do_schedule")],
                                      [Button.inline("« Cancel", b"menu")]])

async def ask_run(e, uid):
    s = state(uid)
    s["step"] = None
    label = dict(ACTIONS).get(s["camp_action"], s["camp_action"])
    opts = s.get("camp_opts", {})
    summary = f"🚀 **Campaign Ready**\n\nAction: **{label}**\n"
    if "post_ref" in opts:
        summary += f"Post msg id: `{opts['msg_id']}`\n"
    if "emoji" in opts:
        summary += f"Emoji: {opts['emoji']}\n"
    if opts.get("btn_index") or opts.get("btn_text"):
        summary += f"Button: `{opts.get('btn_index') or opts.get('btn_text')}`\n"
    if "target" in opts:
        summary += f"Target: `{opts['target'][1]}`\n"
    if "dm_text" in opts:
        summary += f"Text: {opts['dm_text'][:60]}\n"
    if "poll_options" in opts:
        summary += f"Poll options: {opts['poll_options']}\n"
    summary += f"\nAapke accounts jo act karenge: **{len(my_accounts(uid))}**"
    await e.reply(summary, parse_mode="md")
    await e.reply("▶️ Run karo ya schedule karo?",
                  buttons=[[Button.inline("▶️ Run Now", b"run_now"),
                            Button.inline("📅 Schedule", b"schedule_btn")],
                           [Button.inline("« Cancel", b"menu")]])

@bot.on(events.CallbackQuery(pattern=b"^schedule_btn$"))
async def sched_btn(e):
    if not is_admin(e.sender_id):
        return await e.answer(no_access(), alert=True)
    s = state(e.sender_id)
    s["step"] = "sched_time"
    await e.edit("📅 Delay bhejo: `30m` / `2h` / `1d`",
                 buttons=[[Button.inline("« Cancel", b"menu")]])

# .txt file upload for bulk
@bot.on(events.NewMessage(func=lambda e: e.document))
async def txt_upload(e):
    s = state(e.sender_id)
    if s.get("step") != "bulk_input":
        return
    fname = (e.document.attributes[0].file_name if e.document.attributes else "") or ""
    if not fname.endswith(".txt"):
        return await e.reply("❌ Sirf `.txt` (1 session string per line).")
    data = await e.download_media(file=bytes)
    e.text = data.decode("utf-8", errors="ignore")
    await steps(e)

# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

async def main():
    load_scheduled()
    for acc in accounts:
        try:
            await get_client(acc)
        except Exception as ex:
            print(f"[load] {acc['phone']}: {ex}")
    asyncio.create_task(scheduler_loop(bot))
    print(f"[VoteFlow] Running. Accounts: {len(accounts)}, Admins: {len(admins)+1}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    bot.loop.run_until_complete(main())
