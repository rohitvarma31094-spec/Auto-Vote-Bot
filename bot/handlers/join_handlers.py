from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards.inline import account_selection, cancel_button
from database.queries import get_accounts_by_user, get_all_accounts
from pyrogram_client.join import join_chat_for_accounts
from utils.text_formatter import format_join_results, premium_text

router = Router()

class JoinStates(StatesGroup):
    waiting_link = State()
    selecting_accounts = State()

@router.message(Command("join"))
async def join_cmd(message: types.Message, state: FSMContext):
    # Only owner/admin can use
    # Show account selection or auto all?
    accounts = await get_all_accounts() if message.from_user.id == Config.OWNER_ID else await get_accounts_by_user(message.from_user.id)
    if not accounts:
        await message.reply("❌ No active accounts found.")
        return
    await state.update_data(accounts=accounts)
    await message.reply(
        "🟢 Select accounts to join from:\n(Choose one or more)",
        reply_markup=account_selection(accounts, "join_select")
    )
    await state.set_state(JoinStates.selecting_accounts)

@router.callback_query(F.data.startswith("join_select|"))
async def join_select_callback(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data.split("|")[1]
    accounts = (await state.get_data()).get("accounts", [])
    selected_phones = []
    if data == "all":
        selected_phones = [acc["phone"] for acc in accounts if acc["status"] == "active"]
    else:
        phone = data
        # verify phone exists
        for acc in accounts:
            if acc["phone"] == phone and acc["status"] == "active":
                selected_phones.append(phone)
                break
    if not selected_phones:
        await callback.answer("No active accounts selected.", show_alert=True)
        return
    await state.update_data(selected_phones=selected_phones)
    await callback.message.edit_text("🔗 Now send the chat link (username or invite link):")
    await state.set_state(JoinStates.waiting_link)
    await callback.answer()

@router.message(JoinStates.waiting_link)
async def process_join_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    data = await state.get_data()
    phones = data.get("selected_phones", [])
    results = await join_chat_for_accounts(link, phones)
    text = format_join_results(results)
    await message.reply(text)
    await state.clear()