import asyncio
import random
import logging
from pyrogram.errors import FloodWait
from pyrogram_client.client_manager import ClientManager
from pyrogram.enums import MessageMediaType

logger = logging.getLogger(__name__)

async def send_reaction(chat_id: int, message_id: int, emoji: str, phones: list, delay_range=(2, 5)):
    results = {}
    for phone in phones:
        client = ClientManager.get_client(phone)
        if not client:
            results[phone] = "❌ Client inactive"
            continue
        try:
            await client.send_reaction(chat_id, message_id, emoji)
            results[phone] = "✅ Reacted"
        except FloodWait as e:
            wait = e.x + random.randint(1, 3)
            results[phone] = f"⏳ FloodWait {wait}s"
            await asyncio.sleep(wait)
        except Exception as e:
            results[phone] = f"❌ {str(e)[:40]}"
        await asyncio.sleep(random.uniform(*delay_range))
    return results