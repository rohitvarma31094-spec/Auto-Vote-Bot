from aiogram import Router, types
from aiogram.filters import Command
from config import Config
from database.queries import get_accounts_by_user, get_all_accounts, set_admin, add_user, get_all_admins, is_admin
from utils.text_formatter import format_account_list, premium_text

router = Router()

@router.message(Command("checkuser"))
async def check_user_cmd(message: types.Message):
    # Reply to a user or provide user ID
    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        parts = message.text.split()
        if len(parts) > 1:
            try:
                user_id = int(parts[1])
                target_user = types.User(id=user_id, first_name="User", username=None)
            except:
                pass
    if not target_user:
        await message.reply("❌ Please reply to a user's message or provide user ID.\nExample: /checkuser 123456789")
        return
    accounts = await get_accounts_by_user(target_user.id)
    total = len(accounts)
    active = sum(1 for a in accounts if a["status"] == "active")
    restricted = sum(1 for a in accounts if a["status"] == "restricted")
    expired = sum(1 for a in accounts if a["status"] == "expired")
    text = premium_text(
        f"{Config.PREMIUM_EMOJIS['user']} **User:** {target_user.mention or target_user.id}\n"
        f"{Config.PREMIUM_EMOJIS['chart']} **Total Accounts Added:** {total}\n"
        f"{Config.PREMIUM_EMOJIS['green_tick']} **Active:** {active}\n"
        f"{Config.PREMIUM_EMOJIS['warning']} **Restricted:** {restricted}\n"
        f"{Config.PREMIUM_EMOJIS['red_cross']} **Expired:** {expired}"
    )
    await message.reply(text)

@router.message(Command("addadmin"))
async def add_admin_cmd(message: types.Message):
    if message.from_user.id != Config.OWNER_ID:
        await message.reply("⛔ Only owner can add admins.")
        return
    if not message.reply_to_message:
        await message.reply("❌ Reply to a user's message to add them as admin.")
        return
    user = message.reply_to_message.from_user
    await set_admin(user.id, True)
    await add_user(user.id, user.username)
    await message.reply(f"✅ {user.mention} is now an admin.")

@router.message(Command("removeadmin"))
async def remove_admin_cmd(message: types.Message):
    if message.from_user.id != Config.OWNER_ID:
        await message.reply("⛔ Only owner can remove admins.")
        return
    if not message.reply_to_message:
        await message.reply("❌ Reply to a user's message to remove admin status.")
        return
    user = message.reply_to_message.from_user
    await set_admin(user.id, False)
    await message.reply(f"❌ {user.mention} is no longer an admin.")