from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards.inline import account_selection, cancel_button
from database.queries import get_all_accounts, get_accounts_by_user
from pyrogram_client.react import send_reaction
from utils.text_formatter import format_reaction_results

router = Router()

class ReactStates(StatesGroup):
    waiting_reaction_info = State()

@router.message(Command("react"))
async def react_cmd(message: types.Message, state: FSMContext):
    # Format: /react chat_id message_id emoji
    parts = message.text.split()
    if len(parts) < 4:
        await message.reply("Usage: /react chat_id message_id emoji")
        return
    try:
        chat_id = int(parts[1])
        msg_id = int(parts[2])
        emoji = parts[3]
    except:
        await message.reply("❌ Invalid arguments.")
        return
    await state.update_data(chat_id=chat_id, msg_id=msg_id, emoji=emoji)
    accounts = await get_all_accounts() if message.from_user.id == Config.OWNER_ID else await get_accounts_by_user(message.from_user.id)
    if not accounts:
        await message.reply("❌ No accounts found.")
        return
    await message.reply("Select accounts to react:", reply_markup=account_selection(accounts, "react_select"))

@router.callback_query(F.data.startswith("react_select|"))
async def react_select_callback(callback: types.CallbackQuery, state: FSMContext):
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
    result = await send_reaction(data["chat_id"], data["msg_id"], data["emoji"], selected_phones)
    text = format_reaction_results(result)
    await callback.message.edit_text(text)
    await state.clear()
    await callback.answer()