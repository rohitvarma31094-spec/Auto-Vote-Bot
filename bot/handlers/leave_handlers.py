from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.keyboards.inline import account_selection, chat_selection, cancel_button
from database.queries import get_accounts_by_user, get_all_accounts, get_all_joined_chats
from pyrogram_client.leave import leave_all_chats, leave_specific_chat
from utils.text_formatter import format_leave_results, premium_text

router = Router()

@router.message(Command("leaveall"))
async def leaveall_cmd(message: types.Message):
    # Confirm and select accounts
    accounts = await get_all_accounts() if message.from_user.id == Config.OWNER_ID else await get_accounts_by_user(message.from_user.id)
    if not accounts:
        await message.reply("❌ No accounts found.")
        return
    # Ask for confirmation
    await message.reply(
        "⚠️ This will leave **ALL** chats joined via this bot from selected accounts.\n"
        "Select accounts:",
        reply_markup=account_selection(accounts, "leaveall_select")
    )

@router.callback_query(F.data.startswith("leaveall_select|"))
async def leaveall_select(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data.split("|")[1]
    # Get active accounts from DB
    if data == "all":
        accounts = await get_all_accounts()
    else:
        # just one phone
        phone = data
        from database.queries import get_account_by_phone
        acc = await get_account_by_phone(phone)
        accounts = [acc] if acc else []
    phones = [acc["phone"] for acc in accounts if acc["status"] == "active"]
    if not phones:
        await callback.answer("No active accounts selected.", show_alert=True)
        return
    # Execute leave all
    results = await leave_all_chats(phones)
    text = format_leave_results(results)
    await callback.message.edit_text(text)
    await callback.answer()

@router.message(Command("leave"))
async def leave_cmd(message: types.Message):
    # Show list of joined chats for selection
    joined_chats = await get_all_joined_chats()
    if not joined_chats:
        await message.reply("❌ No chats joined via this bot.")
        return
    await message.reply(
        "Select a chat to leave:",
        reply_markup=chat_selection(joined_chats)
    )

@router.callback_query(F.data.startswith("leave_chat|"))
async def leave_chat_callback(callback: types.CallbackQuery):
    chat_id = int(callback.data.split("|")[1])
    # Ask for account selection for this chat
    accounts = await get_all_accounts()
    # Filter accounts that are in this chat (optional)
    # For simplicity, ask user to select accounts
    await callback.message.edit_text(
        f"Select accounts to leave chat {chat_id}:",
        reply_markup=account_selection(accounts, f"leave_specific|{chat_id}")
    )
    await callback.answer()

@router.callback_query(F.data.startswith("leave_specific|"))
async def leave_specific_callback(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    chat_id = int(parts[1])
    data = parts[2] if len(parts) > 2 else "all"
    if data == "all":
        accounts = await get_all_accounts()
    else:
        phone = data
        from database.queries import get_account_by_phone
        acc = await get_account_by_phone(phone)
        accounts = [acc] if acc else []
    phones = [acc["phone"] for acc in accounts if acc["status"] == "active"]
    if not phones:
        await callback.answer("No active accounts selected.", show_alert=True)
        return
    results = await leave_specific_chat(chat_id, phones)
    text = format_leave_results(results)
    await callback.message.edit_text(text)
    await callback.answer()