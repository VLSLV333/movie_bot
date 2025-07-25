from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat
from bot.config import commands_i18n
from bot.utils.logger import Logger

logger = Logger().get_logger()

async def update_bot_commands_for_user(bot: Bot, user_id: int, language: str):
    """
    Update bot commands for a specific user based on their language preference.
    
    Args:
        bot: The bot instance
        user_id: The user's Telegram ID
        language: The language code (en, uk, ru)
    """
    try:
        # Get commands for the specified language
        commands = commands_i18n.get(language, commands_i18n["en"])  # fallback to English
        
        # Convert to BotCommand objects
        bot_commands = [
            BotCommand(command=cmd["command"], description=cmd["description"])
            for cmd in commands
        ]
        
        # Set commands for the specific user
        await bot.set_my_commands(bot_commands, scope=BotCommandScopeChat(chat_id=user_id))
        
        logger.info(f"[User {user_id}] Bot commands updated to language: {language}")
        
    except Exception as e:
        logger.error(f"[User {user_id}] Failed to update bot commands for language {language}: {e}")
