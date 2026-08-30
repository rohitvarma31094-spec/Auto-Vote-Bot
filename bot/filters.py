from aiogram.filters import Filter
from aiogram.types import Message
from config import Config
from database.queries import is_admin

class IsOwner(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id == Config.OWNER_ID

class IsAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id
        if user_id == Config.OWNER_ID:
            return True
        return await is_admin(user_id)