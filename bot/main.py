from bot.utils.logger import Logger
from bot.utils.redis_client import RedisClient
from bot.utils.simple_i18n_setup import setup_simple_i18n

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.config import BOT_TOKEN
from bot.handlers.onboarding_handler import router as onboarding_router
from bot.handlers.main_menu_btns_handler import router as main_menu_router
from bot.handlers.fallback_input_handler import router as fallback_input_handler_router
from bot.handlers.back_btn_handler import router as back_btn_handler_router
from bot.handlers.search_by_name_handler import router as search_by_name_router
from bot.handlers.pagination_handler import router as pagination_handler_router
from bot.handlers.movie_card_handler import router as movie_card_handler_router
from bot.handlers.search_by_genre_handler import router as search_by_genre_handler_router
from bot.handlers.mirror_search_handler import router as mirror_search_router
from bot.handlers.mirror_pagination_handler import router as mirror_pagination_router
from bot.handlers.mirror_watch_download_handler import router as mirror_watch_download_router
from bot.handlers.mirror_language_change_handler import router as mirror_language_change_router
from bot.handlers.bot_lang_change_handler import router as bot_lang_change_router
from bot.handlers.options_btn_handler import router as options_btn_handler_router
from bot.handlers.direct_download_handler import router as direct_download_router
from bot.keyboards.search_type_keyboard import router as search_type_keyboard_router

logger = Logger().get_logger()
logger.info("Bot started and logging initialized ")

bot = Bot(token=BOT_TOKEN or "")
# Create dispatcher with FSM storage
dp = Dispatcher(storage=MemoryStorage())

def setup_routers(disp: Dispatcher):
    disp.include_router(onboarding_router)
    disp.include_router(main_menu_router)
    disp.include_router(search_by_name_router)
    disp.include_router(search_by_genre_handler_router)
    disp.include_router(movie_card_handler_router)
    disp.include_router(pagination_handler_router)
    disp.include_router(back_btn_handler_router)
    disp.include_router(mirror_search_router)
    disp.include_router(mirror_pagination_router)
    disp.include_router(mirror_watch_download_router)
    disp.include_router(mirror_language_change_router)
    disp.include_router(bot_lang_change_router)
    disp.include_router(options_btn_handler_router)
    disp.include_router(direct_download_router)
    disp.include_router(search_type_keyboard_router)
    disp.include_router(fallback_input_handler_router)

async def on_startup():
    await RedisClient.init()
    logger.info(" Redis client initialized!")

async def on_shutdown():
    await RedisClient.close()
    logger.info("Redis client closed!")

async def main():
    try:
        logger.info(" Starting bot...")
        await on_startup()

        # Setup simple I18n middleware BEFORE registering routers
        setup_simple_i18n(dp)
        logger.info("Simple I18n middleware initialized!")

        # Setup routers AFTER I18n middleware
        setup_routers(dp)
        logger.info("Routers registered!")

        await dp.start_polling(bot)
        logger.info("Bot is now running!")
    except Exception as e:
        logger.exception(f"Critical error: {e}")
    finally:
        await on_shutdown()
        logger.info("Bot stopped.")

if __name__ == "__main__":
    asyncio.run(main()) 