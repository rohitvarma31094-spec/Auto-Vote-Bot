from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pyrogram import Client
from pyrogram.errors import PhoneNumberInvalid, SessionExpired
from config import Config
from database.queries import add_account, get_accounts_by_user, add_user, get_account_by_phone
from pyrogram_client.client_manager import ClientManager
from utils.text_formatter import premium_text, format_account_list

router = Router()

class AddAccountStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()  # if 2FA

@router.message(Command("add"))
async def add_account_cmd(message: types.Message, state: FSMContext):
    await message.reply("📱 Please send your phone number with country code (e.g., +1234567890):")
    await state.set_state(AddAccountStates.waiting_phone)

@router.message(AddAccountStates.waiting_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith("+"):
        await message.reply("❌ Please include country code (e.g., +1234567890).")
        return
    # Check if account already exists
    existing = await get_account_by_phone(phone)
    if existing:
        await message.reply(f"⚠️ Account with phone {phone} already added by user {existing['user_id']}.")
        await state.clear()
        return
    # Create Pyrogram client to send code
    try:
        client = Client(
            name=f"temp_{phone}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            phone_number=phone,
            in_memory=True,
        )
        await client.connect()
        sent_code = await client.send_code(phone)
        await state.update_data(phone=phone, client=client, phone_code_hash=sent_code.phone_code_hash)
        await message.reply("📨 Code sent. Please enter the verification code:")
        await state.set_state(AddAccountStates.waiting_code)
    except PhoneNumberInvalid:
        await message.reply("❌ Invalid phone number.")
        await state.clear()
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
        await state.clear()

@router.message(AddAccountStates.waiting_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    client: Client = data.get("client")
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    try:
        await client.sign_in(phone, code, phone_code_hash)
        # Success
        session_string = await client.export_session_string()
        await client.disconnect()
        # Add to database
        await add_account(message.from_user.id, phone, session_string)
        # Start client in manager
        success = await ClientManager.add_new_client(phone, session_string)
        status_icon = Config.PREMIUM_EMOJIS["green_tick"] if success else Config.PREMIUM_EMOJIS["warning"]
        await message.reply(f"{status_icon} Account {phone} added successfully!")
    except SessionExpired:
        await message.reply("❌ Session expired. Please try again.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
    finally:
        await state.clear()

@router.message(Command("myaccounts"))
async def myaccounts_cmd(message: types.Message):
    accounts = await get_accounts_by_user(message.from_user.id)
    if not accounts:
        await message.reply("❌ You have not added any accounts yet.")
        return
    text = format_account_list(accounts, title="📱 Your Accounts")
    await message.reply(text)