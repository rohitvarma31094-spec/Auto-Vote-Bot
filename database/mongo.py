import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

class MongoDB:
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    async def connect(cls):
        # Use tlsCAFile to point to certifi's CA bundle
        cls.client = AsyncIOMotorClient(
            Config.MONGO_URI,
            tls=True,
            tlsCAFile=certifi.where()
        )
        cls.db = cls.client["telegram_bot"]

        # Create indexes
        await cls.db.accounts.create_index("user_id")
        await cls.db.accounts.create_index("phone", unique=True)
        await cls.db.users.create_index("telegram_id", unique=True)
        await cls.db.joined_chats.create_index("chat_id")
        await cls.db.settings.create_index("key", unique=True)

    @classmethod
    async def disconnect(cls):
        if cls.client:
            cls.client.close()
