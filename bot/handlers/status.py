from aiogram import Router, types
from aiogram.filters import Command
from config import Config
from database.queries import get_all_accounts, get_all_joined_chats
from utils.text_formatter import premium_text

router = Router()

@router.message(Command("status"))
async def status_cmd(message: types.Message):
    if message.from_user.id != Config.OWNER_ID:
        await message.reply("⛔ Only owner can view dashboard.")
        return
    accounts = await get_all_accounts()
    total = len(accounts)
    active = sum(1 for a in accounts if a["status"] == "active")
    restricted = sum(1 for a in accounts if a["status"] == "restricted")
    expired = sum(1 for a in accounts if a["status"] == "expired")
    joined_chats = await get_all_joined_chats()
    total_chats = len(joined_chats)
    # top users
    user_counts = {}
    for acc in accounts:
        uid = acc["user_id"]
        user_counts[uid] = user_counts.get(uid, 0) + 1
    top_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_text = "\n".join([f"👤 User ID {uid}: {count} accounts" for uid, count in top_users])
    text = premium_text(
        f"{Config.PREMIUM_EMOJIS['chart']} **Dashboard**\n\n"
        f"{Config.PREMIUM_EMOJIS['user']} **Total Accounts:** {total}\n"
        f"{Config.PREMIUM_EMOJIS['green_tick']} **Active:** {active}\n"
        f"{Config.PREMIUM_EMOJIS['warning']} **Restricted:** {restricted}\n"
        f"{Config.PREMIUM_EMOJIS['red_cross']} **Expired:** {expired}\n"
        f"{Config.PREMIUM_EMOJIS['group']} **Chats Joined:** {total_chats}\n\n"
        f"🏆 **Top Users:**\n{top_text or 'None'}"
    )
    await message.reply(text)