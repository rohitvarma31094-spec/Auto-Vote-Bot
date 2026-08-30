import asyncio
import logging
from pyrogram.errors import FloodWait, SessionExpired
from pyrogram_client.client_manager import ClientManager
from database.queries import update_account_status

logger = logging.getLogger(__name__)

async def keep_alive_loop():
    """Run every 5 minutes to keep sessions alive."""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            for phone, client in ClientManager.clients.items():
                try:
                    # Small action to keep session alive
                    await client.get_me()
                except SessionExpired:
                    logger.warning(f"Session expired for {phone}, marking as expired")
                    await update_account_status(phone, "expired")
                    # Optionally, remove client
                    if phone in ClientManager.clients:
                        del ClientManager.clients[phone]
                except FloodWait as e:
                    logger.info(f"FloodWait for {phone}: {e.x} seconds")
                except Exception as e:
                    logger.error(f"Keep-alive error for {phone}: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Keep-alive loop error: {e}")