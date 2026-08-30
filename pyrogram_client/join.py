import asyncio
import random
import logging
from pyrogram.errors import FloodWait, UserBannedInChannel, ChannelInvalid, PeerIdInvalid
from pyrogram_client.client_manager import ClientManager
from database.queries import update_account_joined_chats, add_joined_chat

logger = logging.getLogger(__name__)

async def join_chat_for_accounts(chat_link: str, phones: list, delay_range=(3, 7)):
    """
    Send join request from specified accounts.
    Returns dict: {phone: status_message}
    """
    results = {}
    for phone in phones:
        client = ClientManager.get_client(phone)
        if not client:
            results[phone] = "❌ Client not active"
            continue
        try:
            # Try to join
            chat = await client.join_chat(chat_link)
            chat_id = chat.id
            chat_title = chat.title
            chat_type = "channel" if hasattr(chat, "username") else "group"
            # Update DB
            await update_account_joined_chats(phone, chat_id)
            # Store chat record
            await add_joined_chat(chat_id, chat_title, chat_type, [phone])
            results[phone] = "✅ Joined successfully"
        except UserBannedInChannel:
            results[phone] = "🚫 Banned from this chat"
        except ChannelInvalid:
            results[phone] = "❌ Invalid chat link"
        except PeerIdInvalid:
            results[phone] = "❌ Peer ID invalid"
        except FloodWait as e:
            wait = e.x + random.randint(1, 5)
            results[phone] = f"⏳ FloodWait: {wait}s"
            await asyncio.sleep(wait)
        except Exception as e:
            results[phone] = f"❌ Error: {str(e)[:50]}"
        # Delay between accounts
        if phones.index(phone) != len(phones) - 1:
            await asyncio.sleep(random.uniform(*delay_range))
    return results