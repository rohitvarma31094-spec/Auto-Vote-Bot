from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards.inline import account_selection, cancel_button
from database.queries import get_all_accounts, get_accounts_by_user
from pyrogram_client.vote import vote_poll, vote_button_bot
from utils.text_formatter import format_vote_results

router = Router()

class VoteStates(StatesGroup):
    waiting_poll_info = State()
    waiting_button_info = State()
    selecting_accounts = State()

@router.message(Command("vote"))
async def vote_cmd(message: types.Message, state: FSMContext):
    accounts = await get_all_accounts() if message.from_user.id == Config.OWNER_ID else await get_accounts_by_user(message.from_user.id)
    if not accounts:
        await message.reply("❌ No accounts found.")
        return
    await state.update_data(accounts=accounts)
    # Ask for type: poll or button bot?
    await message.reply(
        "Select vote type:\n"
        "1️⃣ Normal Poll (reply to poll message with /vote_poll)\n"
        "2️⃣ Voting Bot Button (send /vote_button chat_id message_id button_text)",
        reply_markup=cancel_button()
    )
    # We'll use separate handlers for simplicity: we can have /votepoll and /votebutton
    # Implement two subcommands to avoid complex state.
    # For brevity, we'll implement /votepoll and /votebutton directly.

@router.message(Command("votepoll"))
async def vote_poll_cmd(message: types.Message, state: FSMContext):
    # Expect format: /votepoll chat_id message_id option_index
    parts = message.text.split()
    if len(parts) < 4:
        await message.reply("Usage: /votepoll chat_id message_id option_index (0-based)")
        return
    try:
        chat_id = int(parts[1])
        msg_id = int(parts[2])
        option = int(parts[3])
    except:
        await message.reply("❌ Invalid arguments. Use integers.")
        return
    await state.update_data(vote_type="poll", chat_id=chat_id, msg_id=msg_id, option=option)
    # Ask for account selection
    accounts = await get_all_accounts() if message.from_user.id == Config.OWNER_ID else await get_accounts_by_user(message.from_user.id)
    await message.reply("Select accounts to vote:", reply_markup=account_selection(accounts, "vote_select"))

@router.message(Command("votebutton"))
async def vote_button_cmd(message: types.Message, state: FSMContext):
    # /votebutton chat_id message_id button_text
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.reply("Usage: /votebutton chat_id message_id button_text")
        return
    try:
        chat_id = int(parts[1])
        msg_id = int(parts[2])
        button_text = parts[3]
    except:
        await message.reply("❌ Invalid arguments.")
        return
    await state.update_data(vote_type="button", chat_id=chat_id, msg_id=msg_id, button_text=button_text)
    accounts = await get_all_accounts() if message.from_user.id == Config.OWNER_ID else await get_accounts_by_user(message.from_user.id)
    await message.reply("Select accounts to vote:", reply_markup=account_selection(accounts, "vote_select"))

@router.callback_query(F.data.startswith("vote_select|"))
async def vote_select_callback(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data.split("|")[1]
    accounts = (await state.get_data()).get("accounts", [])
    selected_phones = []
    if data == "all":
        selected_phones = [acc["phone"] for acc in accounts if acc["status"] == "active"]
    else:
        phone = data
        for acc in accounts:
            if acc["phone"] == phone and acc["status"] == "active":
                selected_phones.append(phone)
                break
    if not selected_phones:
        await callback.answer("No active accounts selected.", show_alert=True)
        return
    data = await state.get_data()
    vote_type = data.get("vote_type")
    if vote_type == "poll":
        result = await vote_poll(data["chat_id"], data["msg_id"], data["option"], selected_phones)
    else:
        result = await vote_button_bot(data["chat_id"], data["msg_id"], data["button_text"], selected_phones)
    text = format_vote_results(result)
    await callback.message.edit_text(text)
    await state.clear()
    await callback.answer()