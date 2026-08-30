import asyncio
import random
import logging
from pyrogram.errors import FloodWait
from pyrogram_client.client_manager import ClientManager
from pyrogram.types import Message, Poll
from pyrogram.enums import PollType

logger = logging.getLogger(__name__)

async def vote_poll(chat_id: int, message_id: int, option_index: int, phones: list, delay_range=(2, 5)):
    """
    Vote in a normal poll.
    option_index: 0-based index of the option to vote for.
    """
    results = {}
    for phone in phones:
        client = ClientManager.get_client(phone)
        if not client:
            results[phone] = "❌ Client inactive"
            continue
        try:
            await client.vote_poll(chat_id, message_id, option_index)
            results[phone] = "✅ Voted"
        except FloodWait as e:
            wait = e.x + random.randint(1, 3)
            results[phone] = f"⏳ FloodWait {wait}s"
            await asyncio.sleep(wait)
        except Exception as e:
            results[phone] = f"❌ {str(e)[:40]}"
        await asyncio.sleep(random.uniform(*delay_range))
    return results

async def vote_button_bot(chat_id: int, message_id: int, button_text: str, phones: list, delay_range=(2, 5)):
    """
    Vote in custom voting bots by clicking inline button.
    button_text: exact text of the button to click.
    """
    results = {}
    for phone in phones:
        client = ClientManager.get_client(phone)
        if not client:
            results[phone] = "❌ Client inactive"
            continue
        try:
            # Get the message
            msg: Message = await client.get_messages(chat_id, message_id)
            if not msg.reply_markup:
                results[phone] = "❌ No inline keyboard"
                continue
            # Find the button
            for row in msg.reply_markup.inline_keyboard:
                for btn in row:
                    if btn.text == button_text:
                        await client.request_callback_query(chat_id, msg.id, btn.callback_data)
                        results[phone] = "✅ Voted"
                        break
                else:
                    continue
                break
            else:
                results[phone] = "❌ Button not found"
        except FloodWait as e:
            wait = e.x + random.randint(1, 3)
            results[phone] = f"⏳ FloodWait {wait}s"
            await asyncio.sleep(wait)
        except Exception as e:
            results[phone] = f"❌ {str(e)[:40]}"
        await asyncio.sleep(random.uniform(*delay_range))
    return results