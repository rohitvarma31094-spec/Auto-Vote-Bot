import asyncio
from pyrogram import Client
from pyrogram.errors import FloodWait, SessionExpired, UserBannedInChannel
from typing import Dict, Optional
import logging
from config import Config
from database.queries import get_all_accounts, update_account_status

logger = logging.getLogger(__name__)

class ClientManager:
    clients: Dict[str, Client] = {}  # phone -> Client instance

    @classmethod
    async def start_all_clients(cls):
        """Load all accounts from DB and start Pyrogram clients."""
        accounts = await get_all_accounts()
        for acc in accounts:
            phone = acc["phone"]
            session_string = acc["session_string"]
            try:
                client = Client(
                    name=phone,
                    session_string=session_string,
                    api_id=Config.API_ID,
                    api_hash=Config.API_HASH,
                    workdir=Config.SESSION_FOLDER,
                )
                await client.start()
                cls.clients[phone] = client
                # Update last_active
                await update_account_status(phone, "active")
                logger.info(f"Started client for {phone}")
            except Exception as e:
                logger.error(f"Failed to start client {phone}: {e}")
                await update_account_status(phone, "expired")
        logger.info(f"Total active clients: {len(cls.clients)}")

    @classmethod
    async def stop_all_clients(cls):
        for phone, client in cls.clients.items():
            try:
                await client.stop()
            except:
                pass
        cls.clients.clear()

    @classmethod
    def get_client(cls, phone: str) -> Optional[Client]:
        return cls.clients.get(phone)

    @classmethod
    async def add_new_client(cls, phone: str, session_string: str) -> bool:
        """Create and start a client for newly added account."""
        try:
            client = Client(
                name=phone,
                session_string=session_string,
                api_id=Config.API_ID,
                api_hash=Config.API_HASH,
                workdir=Config.SESSION_FOLDER,
            )
            await client.start()
            cls.clients[phone] = client
            return True
        except Exception as e:
            logger.error(f"Failed to start new client {phone}: {e}")
            return False

    @classmethod
    async def restart_client(cls, phone: str):
        """Stop and restart a client (e.g., after reconnect)."""
        if phone in cls.clients:
            try:
                await cls.clients[phone].stop()
            except:
                pass
            del cls.clients[phone]
        # Re-fetch session string from DB
        from database.queries import get_account_by_phone
        acc = await get_account_by_phone(phone)
        if acc:
            session_string = acc["session_string"]
            try:
                client = Client(
                    name=phone,
                    session_string=session_string,
                    api_id=Config.API_ID,
                    api_hash=Config.API_HASH,
                    workdir=Config.SESSION_FOLDER,
                )
                await client.start()
                cls.clients[phone] = client
                await update_account_status(phone, "active")
                logger.info(f"Restarted client {phone}")
            except Exception as e:
                logger.error(f"Failed to restart {phone}: {e}")
                await update_account_status(phone, "expired")