import asyncio
import random
import logging
from pyrogram.errors import FloodWait
from pyrogram_client.client_manager import ClientManager
from database.queries import get_all_joined_chats, delete_joined_chat, update_account_joined_chats

logger = logging.getLogger(__name__)

async def leave_all_chats(phones: list, delay_range=(2, 5)):
    """Leave all chats that were joined via this bot (from DB)."""
    joined_chats = await get_all_joined_chats()
    results = {}
    for chat_doc in joined_chats:
        chat_id = chat_doc["chat_id"]
        for phone in phones:
            client = ClientManager.get_client(phone)
            if not client:
                results[(phone, chat_id)] = "❌ Client inactive"
                continue
            try:
                await client.leave_chat(chat_id)
                # Remove from account's joined_chats
                await update_account_joined_chats(phone, chat_id, remove=True)
                results[(phone, chat_id)] = "✅ Left"
            except FloodWait as e:
                wait = e.x + random.randint(1, 3)
                results[(phone, chat_id)] = f"⏳ FloodWait {wait}s"
                await asyncio.sleep(wait)
            except Exception as e:
                results[(phone, chat_id)] = f"❌ {str(e)[:40]}"
            await asyncio.sleep(random.uniform(*delay_range))
    # Remove chats that no account is in? (optional)
    return results

async def leave_specific_chat(chat_id: int, phones: list):
    """Leave a specific chat from selected accounts."""
    results = {}
    for phone in phones:
        client = ClientManager.get_client(phone)
        if not client:
            results[phone] = "❌ Client inactive"
            continue
        try:
            await client.leave_chat(chat_id)
            await update_account_joined_chats(phone, chat_id, remove=True)
            results[phone] = "✅ Left"
        except FloodWait as e:
            wait = e.x + random.randint(1, 3)
            results[phone] = f"⏳ FloodWait {wait}s"
            await asyncio.sleep(wait)
        except Exception as e:
            results[phone] = f"❌ {str(e)[:40]}"
        await asyncio.sleep(random.uniform(1, 3))
    return results