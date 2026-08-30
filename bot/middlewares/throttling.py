from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
import time

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit=2):
        self.rate_limit = rate_limit
        self.user_last_usage = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = event.from_user.id
        now = time.time()
        if user_id in self.user_last_usage and now - self.user_last_usage[user_id] < self.rate_limit:
            await event.reply("⏳ Please wait before using this command again.", reply_to_message_id=event.message_id)
            return
        self.user_last_usage[user_id] = now
        return await handler(event, data)