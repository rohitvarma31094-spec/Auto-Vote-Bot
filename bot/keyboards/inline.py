from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import Config

def main_menu(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['button_join']} Join", callback_data="join_menu"),
        InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['button_leave']} Leave", callback_data="leave_menu"),
    )
    builder.row(
        InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['button_vote']} Vote", callback_data="vote_menu"),
        InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['button_react']} React", callback_data="react_menu"),
    )
    builder.row(
        InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['button_settings']} Settings", callback_data="settings_menu"),
    )
    builder.row(
        InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['info']} My Accounts", callback_data="myaccounts"),
    )
    if user_id == Config.OWNER_ID:
        builder.row(
            InlineKeyboardButton(text=f"{Config.PREMIUM_EMOJIS['chart']} Dashboard", callback_data="status"),
        )
    return builder.as_markup()

def account_selection(accounts: list, action: str) -> InlineKeyboardMarkup:
    """Build keyboard with account phones for selection."""
    builder = InlineKeyboardBuilder()
    for acc in accounts:
        phone = acc["phone"]
        status_icon = Config.PREMIUM_EMOJIS["green_tick"] if acc["status"] == "active" else Config.PREMIUM_EMOJIS["red_cross"]
        builder.row(
            InlineKeyboardButton(
                text=f"{status_icon} {phone}",
                callback_data=f"{action}|{phone}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="✅ Select All", callback_data=f"{action}|all"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel"),
    )
    return builder.as_markup()

def chat_selection(chats: list) -> InlineKeyboardMarkup:
    """For leaving specific chat: show list of joined chats."""
    builder = InlineKeyboardBuilder()
    for chat in chats:
        title = chat.get("chat_title", f"Chat {chat['chat_id']}")
        builder.row(
            InlineKeyboardButton(
                text=f"{Config.PREMIUM_EMOJIS['group']} {title[:30]}",
                callback_data=f"leave_chat|{chat['chat_id']}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel"),
    )
    return builder.as_markup()

def cancel_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="cancel"))
    return builder.as_markup()