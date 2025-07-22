import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode

from config import Config
from handlers import commands, admin, afk

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def main():
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return

    bot = Bot(token=Config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # Register handlers
    dp.include_router(commands.router)
    dp.include_router(admin.router)
    dp.include_router(afk.router)

    # Start periodic AFK checks
    async def schedule_afk_checks():
        while True:
            await asyncio.sleep(Config.AFK_TIMEOUT_MINUTES * 60)
            await afk.periodic_afk_check(bot)

    asyncio.create_task(schedule_afk_checks())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())