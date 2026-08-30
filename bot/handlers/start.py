from aiogram import Router, types
from aiogram.filters import Command
from bot.keyboards.inline import main_menu
from database.queries import add_user
from utils.text_formatter import premium_text

router = Router()

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    await add_user(user.id, user.username)
    text = premium_text(
        f"{Config.PREMIUM_EMOJIS['sparkle']} **Welcome to Multi-Account Bot!**\n\n"
        f"👤 User: {user.mention}\n"
        f"🆔 ID: `{user.id}`\n\n"
        "Use the buttons below to manage your accounts and perform actions."
    )
    await message.reply(text, reply_markup=main_menu(user.id))