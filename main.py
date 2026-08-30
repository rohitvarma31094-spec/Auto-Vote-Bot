import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import Config
from database.mongo import MongoDB
from pyrogram_client.client_manager import ClientManager
from pyrogram_client.session_keeper import keep_alive_loop

# Import routers
from bot.handlers import start, account, admin, join_handlers, leave_handlers, vote_handlers, react_handlers, status
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from utils.logger import setup_logger

logger = setup_logger()

async def main():
    # Connect to MongoDB
    await MongoDB.connect()
    logger.info("Connected to MongoDB")

    # Initialize bot and dispatcher
    bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()

    # Register middlewares
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    dp.message.middleware(ThrottlingMiddleware(rate_limit=2))

    # Register routers
    dp.include_router(start.router)
    dp.include_router(account.router)
    dp.include_router(admin.router)
    dp.include_router(join_handlers.router)
    dp.include_router(leave_handlers.router)
    dp.include_router(vote_handlers.router)
    dp.include_router(react_handlers.router)
    dp.include_router(status.router)

    # Start all Pyrogram clients
    await ClientManager.start_all_clients()

    # Start keep-alive task
    asyncio.create_task(keep_alive_loop())

    logger.info("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")