from aiogram import Router, types, F
from aiohttp import ClientSession
from bot.utils.logger import Logger
from bot.helpers.render_mirror_card import get_mirror_language_selection_keyboard, get_language_display_name, render_mirror_card, get_message_id_from_redis
from bot.utils.redis_client import RedisClient

router = Router()
logger = Logger().get_logger()

@router.callback_query(F.data.startswith("CLM:"))
async def change_language_mirror_handler(query: types.CallbackQuery):
    """Handle 'Change language' button click on mirror card"""
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in change_language_mirror_handler")
        return
    
    user_id = query.from_user.id
    # Parse callback data: CLM:stream_id
    stream_id = query.data.split("CLM:")[1]
    
    logger.info(f"[User {user_id}] Requested language change for mirror: {stream_id}")
    
    # Store the stream_id temporarily in Redis for the language selection handler
    try:
        redis = RedisClient.get_client()
        await redis.set(f"lang_change_stream:{user_id}", stream_id, ex=300)  # 5 minutes TTL
    except Exception as e:
        logger.warning(f"[User {user_id}] Failed to store stream_id for language change: {e}")
    
    # Show language selection keyboard in a new message
    keyboard = get_mirror_language_selection_keyboard()
    
    if query.message is not None:
        lang_selection_msg = await query.message.answer(
            "🌍 Select your preferred language for watching movies:",
            reply_markup=keyboard
        )
        # Store the language selection message ID for later deletion
        await query.answer()
        return lang_selection_msg
    else:
        logger.error("query.message is None, cannot send language selection message")
        await query.answer("❌ Error: Cannot show language options")
        return None

@router.callback_query(F.data.startswith("mirror_select_lang:"))
async def mirror_select_language_handler(query: types.CallbackQuery):
    """Handle language selection in mirror context"""
    if query is None or query.data is None:
        logger.error("CallbackQuery or its data is None in mirror_select_language_handler")
        return
    
    user_id = query.from_user.id
    selected_language = query.data.split("mirror_select_lang:")[1]
    
    logger.info(f"[User {user_id}] Selected language in mirror context: {selected_language}")
    
    # Delete the language selection message
    if query.message is not None:
        try:
            await query.message.delete()
        except Exception as e:
            logger.warning(f"[User {user_id}] Failed to delete language selection message: {e}")
    
    # Update user's preferred language in backend
    try:
        async with ClientSession() as session:
            async with session.put(
                "https://moviebot.click/users/language",
                json={
                    "telegram_id": user_id,
                    "preferred_language": selected_language
                }
            ) as resp:
                if resp.status == 200:
                    user_data = await resp.json()
                    logger.info(f"[User {user_id}] Successfully updated language to: {selected_language}")

                    # Get the language display name
                    language_display = get_language_display_name(selected_language)

                    await query.answer(f"✅ Language updated to: {language_display}\n\nPress 'Watch' or 'Download' - language will be as you just selected")
                    return

                else:
                    logger.error(f"[User {user_id}] Failed to update language: {resp.status}")
                    # Send error message
                    if query.message is not None:
                        await query.message.answer("❌ Couldn't update language, please try later")
                            
    except Exception as e:
        logger.error(f"[User {user_id}] Exception during language update: {e}")
        # Send error message
        if query.message is not None:
            await query.message.answer("❌ Couldn't update language, please try later")
    
    await query.answer() 