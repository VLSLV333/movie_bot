import json
from aiogram import Router, types, F
from aiohttp import ClientSession
from bot.utils.logger import Logger
from bot.helpers.render_mirror_card import get_mirror_language_selection_keyboard, get_language_display_name, render_mirror_card, get_message_id_from_redis
from bot.utils.redis_client import RedisClient
from bot.utils.message_utils import smart_edit_or_send

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
                    
                    # Try to find and update the original mirror card using Redis
                    try:
                        redis = RedisClient.get_client()
                        
                        # Get the stream_id that was stored when the language change was requested
                        stream_id = await redis.get(f"lang_change_stream:{user_id}")
                        
                        if stream_id:
                            # Get the message ID from Redis using stream_id and user_id
                            message_id = await get_message_id_from_redis(stream_id, user_id)
                            
                            if message_id and query.bot is not None:
                                # Get the current message to extract the title
                                try:
                                    current_message = await query.bot.get_message(
                                        chat_id=query.from_user.id,
                                        message_id=message_id
                                    )
                                    
                                    if current_message and current_message.caption:
                                        # Extract the title from the current caption
                                        caption_lines = current_message.caption.split('\n')
                                        if len(caption_lines) >= 1:
                                            title_line = caption_lines[0]  # First line is the title
                                            
                                            # Create new caption with updated language
                                            new_caption = f"{title_line}\n\nPreferred language to watch: {language_display}"
                                            
                                            # Update only the caption
                                            await query.bot.edit_message_caption(
                                                chat_id=query.from_user.id,
                                                message_id=message_id,
                                                caption=new_caption,
                                                parse_mode="HTML"
                                            )
                                            
                                            logger.info(f"[User {user_id}] Successfully updated language display to: {selected_language}")
                                            await query.answer(f"✅ Language updated to: {language_display}")
                                            return
                                            
                                except Exception as e:
                                    logger.warning(f"[User {user_id}] Failed to get or update message: {e}")
                                    # Fallback to success message
                                    await query.message.answer(f"✅ Language updated to: {language_display}")
                            else:
                                logger.warning(f"[User {user_id}] No message ID found in Redis for stream_id: {stream_id}")
                                await query.message.answer(f"✅ Language updated to: {language_display}")
                        else:
                            logger.warning(f"[User {user_id}] No stream_id found in Redis for language change")
                            await query.message.answer(f"✅ Language updated to: {language_display}")
                            
                    except Exception as e:
                        logger.error(f"[User {user_id}] Exception during Redis lookup: {e}")
                        await query.message.answer(f"✅ Language updated to: {language_display}")
                    
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