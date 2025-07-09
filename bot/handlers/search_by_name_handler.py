from aiogram import Router, types, F
from aiogram_i18n import I18nContext

from bot.locales.keys import SEARCH_BY_NAME_PROMPT, NO_SEARCH_RESULTS_TRY_AGAIN
from bot.utils.logger import Logger
from bot.utils.session_manager import SessionManager
from bot.helpers.back_button import get_back_button_keyboard
from aiogram.filters import Filter
from bot.search.search_strategy import SearchByNameStrategy
from bot.search.user_search_context import UserSearchContext
from bot.services.tmdb_service import TMDBService
from bot.helpers.render_movie_card import render_movie_card
from bot.helpers.render_navigation_panel import render_navigation_panel
from bot.helpers.back_to_main_menu_btn import add_back_to_main_menu_button
from aiogram.exceptions import TelegramBadRequest
from bot.utils.user_service import UserService
from bot.utils.message_utils import smart_edit_or_send

router = Router()
logger = Logger().get_logger()
tmdb_service = TMDBService()


class SearchInputStateFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        state = await SessionManager.get_state(message.from_user.id)
        return state == "search_by_name:waiting"


@router.callback_query(F.data == "search_by_name")
async def search_by_name_handler(query: types.CallbackQuery, i18n: I18nContext):
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Selected 'Search by Name'")

    await SessionManager.clear_state(user_id)
    await SessionManager.set_state(user_id, "search_by_name:waiting")

    keyboard = get_back_button_keyboard("search",i18n=i18n)

    # Use smart edit or send utility
    await smart_edit_or_send(
        message=query,
        text=i18n.get(SEARCH_BY_NAME_PROMPT),
        reply_markup=keyboard
    )

    await query.answer()

@router.message(F.text, SearchInputStateFilter())
async def handle_user_search_text_input(message: types.Message, i18n: I18nContext):
    # Here we handle only input with state state == "search_by_name:waiting"
    user_id = message.from_user.id
    await SessionManager.clear_state(user_id)
    query = message.text.strip()
    logger.info(f"[User {user_id}] Text input received: '{query}' (state: search_by_name:waiting)")

    # Get user's preferred language dynamically
    user_lang = await UserService.get_user_preferred_language(user_id)

    strategy = SearchByNameStrategy(query=query, language=user_lang)
    context = UserSearchContext(strategy=strategy, language=user_lang)

    await process_search(context, message,i18n=i18n)

async def process_search(context: UserSearchContext, message: types.Message, i18n: I18nContext):
    context = context
    message_ids = []
    pagination_message_id = None
    top_pagination_message_id = None

    try:
        movies = await context.get_next_movies(tmdb_service)

        if not movies:
            await SessionManager.set_state(message.from_user.id, "search_by_name:waiting")
            logger.info(f"[User {message.from_user.id}] Prompted to input movie name in bot.handlers.search process_search (state set: search_by_name:waiting)")
            keyboard = get_back_button_keyboard('search',i18n=i18n)
            await message.answer(
                i18n.get(NO_SEARCH_RESULTS_TRY_AGAIN),
                reply_markup=keyboard
            )
            return

        # Top navigation panel
        try:
            nav_text_top, nav_keyboard_top = render_navigation_panel(context, position="top", click_source=None,i18n=i18n)
            nav_keyboard_top = add_back_to_main_menu_button(nav_keyboard_top,i18n=i18n)
            top_nav_msg = await message.answer(nav_text_top, reply_markup=nav_keyboard_top)
            top_pagination_message_id = top_nav_msg.message_id
        except TelegramBadRequest as e:
            logger.error(
                f"[User {message.from_user.id}] Error sending top pagination panel in bot.helpers.handle_search_query process_search: {e}"
            )

        # Movie cards
        for movie in movies:
            text, keyboard, poster_url = await render_movie_card(movie, is_expanded=False,i18n=i18n)
            try:
                movie_card =  await message.answer_photo(
                    photo=poster_url,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                message_ids.append(movie_card.message_id)
                logger.info(f"[User {message.from_user.id}] Movie card sent: ID {movie_card.message_id}")
            except TelegramBadRequest as e:
                logger.error(f"Error sending movie card: {e}")

        # Bottom navigation panel
        try:
            nav_text, nav_keyboard = render_navigation_panel(context, position="bottom", click_source=None,i18n=i18n)
            nav_keyboard = add_back_to_main_menu_button(nav_keyboard,i18n=i18n)
            bottom_nav_msg = await message.answer(nav_text, reply_markup=nav_keyboard)
            pagination_message_id = bottom_nav_msg.message_id
        except TelegramBadRequest as e:
            logger.error(
                f"[User {message.from_user.id}] Error sending bot pagination panel in bot.helpers.handle_search_query process_search: {e}")

    except Exception as e:
        logger.error(f"Unexpected error in process_search: {e}")

    finally:
        if context.current_results:
            try:
                await SessionManager.save_context(
                    user_id=message.from_user.id,
                    context=context,
                    current_cards_message_ids=message_ids,
                    pagination_message_id=pagination_message_id,
                    top_pagination_message_id=top_pagination_message_id
                )
                logger.info(
                    f"[User {message.from_user.id}] Session saved to Redis: page {context.current_page}, "
                    f"idx {context.current_result_idx}, cards {message_ids}, panel {pagination_message_id}, "
                    f"top_panel {top_pagination_message_id}"
                )
            except Exception as e:
                logger.error(f"Redis error while saving session in bot.helpers.handle_search_query process_search: {e}")

