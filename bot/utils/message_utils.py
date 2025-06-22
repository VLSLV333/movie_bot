from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from typing import Optional, Union
from bot.utils.logger import Logger

logger = Logger().get_logger()

async def smart_edit_or_send(
    message: Union[types.Message, types.CallbackQuery],
    text: str,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None
) -> types.Message:
    """
    Intelligently edit a message if possible, otherwise send a new one.
    
    Args:
        message: The message or callback query to work with
        text: The text content to display
        reply_markup: Optional keyboard markup
        parse_mode: Optional parse mode (HTML, Markdown, etc.)
        
    Returns:
        The message object (either edited or new)
    """
    
    # Extract the actual message from callback query if needed
    if isinstance(message, types.CallbackQuery):
        actual_message = message.message
    else:
        actual_message = message
    
    if not actual_message:
        # If no message available, we have to send a new one
        if isinstance(message, types.CallbackQuery):
            # This should not happen in normal flow, but handle it gracefully
            logger.warning("No message available in callback query, cannot send new message")
            raise ValueError("No message available to work with")
        else:
            return await message.answer(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
    
    # Check if the message can be edited (only if it's a proper Message)
    can_edit = False
    if isinstance(actual_message, types.Message):
        can_edit = _can_edit_message(actual_message)
    
    if can_edit and isinstance(actual_message, types.Message):
        try:
            # Try to edit the message
            await actual_message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            logger.debug(f"Successfully edited message {actual_message.message_id}")
            return actual_message
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                # Message content is the same, no need to edit
                logger.debug(f"Message {actual_message.message_id} not modified, keeping original")
                return actual_message
            else:
                # Other edit error, fall back to sending new message
                logger.warning(f"Failed to edit message {actual_message.message_id}: {e}")
                can_edit = False
        except Exception as e:
            # Unexpected error, fall back to sending new message
            logger.error(f"Unexpected error editing message {actual_message.message_id}: {e}")
            can_edit = False
    
    # If we can't edit or edit failed, send a new message
    if not can_edit:
        try:
            # Use the original message or callback query to send new message
            if isinstance(message, types.CallbackQuery) and message.message:
                new_message = await message.message.answer(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            elif isinstance(message, types.Message):
                new_message = await message.answer(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            else:
                # Fallback: try to use the actual_message if it's accessible
                if isinstance(actual_message, types.Message):
                    new_message = await actual_message.answer(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                else:
                    raise ValueError("No accessible message to send new message")
            
            logger.debug(f"Sent new message {new_message.message_id} instead of editing")
            return new_message
        except Exception as e:
            logger.error(f"Failed to send new message: {e}")
            raise
    
    # This should never be reached, but just in case
    raise RuntimeError("Unexpected state in smart_edit_or_send")

def _can_edit_message(message: types.Message) -> bool:
    """
    Check if a message can be edited.
    
    Args:
        message: The message to check
        
    Returns:
        True if the message can be edited, False otherwise
    """
    # Messages with media (photos, videos, animations, etc.) cannot be edited
    # unless they also have text content
    has_media = (
        message.photo or 
        message.video or 
        message.animation or 
        message.document or 
        message.audio or 
        message.voice or 
        message.video_note or 
        message.sticker
    )
    
    has_text = bool(message.text or message.caption)
    
    # Can edit if:
    # 1. No media (text-only message)
    # 2. Has media AND has text (can edit the text/caption)
    # 3. Has media but no text (cannot edit)
    
    if not has_media:
        return True  # Text-only message, can edit
    
    if has_media and has_text:
        return True  # Media with text, can edit the text
    
    return False  # Media without text, cannot edit

async def safe_edit_text(
    message: Union[types.Message, types.CallbackQuery],
    text: str,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None
) -> Optional[types.Message]:
    """
    Safely edit text with fallback to new message.
    Returns None if both edit and send fail.
    """
    try:
        return await smart_edit_or_send(message, text, reply_markup, parse_mode)
    except Exception as e:
        logger.error(f"Both edit and send failed: {e}")
        return None 