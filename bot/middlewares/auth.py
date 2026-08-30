from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from config import Config
from database.queries import is_admin

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        # Allow if owner or admin
        if user_id == Config.OWNER_ID or await is_admin(user_id):
            return await handler(event, data)
        # Else, only allow /start, /add, /myaccounts for normal users
        if event.text and event.text.startswith(("/start", "/add", "/myaccounts")):
            return await handler(event, data)
        await event.answer("⛔ You don't have permission to use this command.", show_alert=True)