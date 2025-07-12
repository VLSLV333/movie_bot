import hashlib
import traceback
import json
from aiogram import Router, types, F
from aiogram.utils.i18n import gettext
from aiohttp import ClientSession
from bot.utils.session_manager import SessionManager
from bot.locales.keys import (
    SOMETHING_WENT_WRONG_TRY_MAIN_MENU, SEARCHING_IN_PROGRESS, SESSION_EXPIRED_RESTART_SEARCH,
    FAILED_TO_SEARCH_MIRRORS_TRY_AGAIN, UNEXPECTED_ERROR_MIRROR_SEARCH_TRY_AGAIN, 
    NO_MIRROR_RESULTS_TRY_ANOTHER_MOVIE
)
from bot.search.mirror_search_session import MirrorSearchSession
from bot.handlers.main_menu_btns_handler import get_main_menu_keyboard
from bot.keyboards.mirror_navigation_keyboard import get_mirror_navigation_keyboard
from bot.helpers.render_mirror_card import render_mirror_card_batch, store_message_id_in_redis
from bot.utils.logger import Logger
from bot.utils.redis_client import RedisClient
from bot.utils.user_service import UserService

router = Router()
logger = Logger().get_logger()

MIRROR_SEARCH_API_URL = "https://moviebot.click/mirror/search"

#TODO: this endpoint is not yet implemented in backend! Add new mirrors first
MIRROR_NEXT_API_URL = "https://moviebot.click/mirror/search/next"

DEFAULT_MIRROR_INDEX = 0

async def fetch_next_mirror_results(query: str, lang: str, excluded_mirrors: list[str]) -> dict | None:
    payload = {
        "query": query,
        "lang": lang,
        "excluded": excluded_mirrors
    }
    try:
        async with ClientSession() as session:
            async with session.post(MIRROR_NEXT_API_URL, json=payload) as resp:
                if resp.status == 200:
                    next_batch = await resp.json()
                    return next_batch[0] if next_batch else None
                else:
                    logger.error(f"[MirrorPrefetch] Mirror next search failed: {resp.status} - {await resp.text()}")
    except Exception as e:
        logger.exception(f"[MirrorPrefetch] Exception: {e}")
    return None

@router.callback_query(F.data.startswith("select_movie_card:"))
async def handle_mirror_search(query: types.CallbackQuery):
    redis = RedisClient.get_client()

    main_menu_keyboard = get_main_menu_keyboard()
    if not query.data:
        await query.answer(gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU), reply_markup=main_menu_keyboard)
        return
    parts = query.data.split(":")
    # select_movie_card:{movie_id} or select_movie_card:{movie_id}:{flag}
    movie_id = parts[1]
    skip_db_lookup = len(parts) > 2 and parts[2] == "y"

    movie_json = await redis.get(f"movie_info:{movie_id}")
    if not movie_json:
        await query.answer(gettext(SOMETHING_WENT_WRONG_TRY_MAIN_MENU), reply_markup=main_menu_keyboard)
        return
    movie = json.loads(movie_json)

    tmdb_id = int(movie_id)

    await query.answer(gettext(SEARCHING_IN_PROGRESS))
    logger.info(f"[User {query.from_user.id}] Initiating mirror search for: '{movie.get('original_title')}' (skip_db_lookup={skip_db_lookup})")

    # Retrieve movie title from stored session (you may pass it directly in a real scenario)
    session = await SessionManager.get_user_session(query.from_user.id)
    if not session:
        if query.message:
            await query.message.answer(
                gettext(SESSION_EXPIRED_RESTART_SEARCH),
                reply_markup=main_menu_keyboard
            )
        await query.answer()
        return

    # Get user's preferred language from backend
    user_lang = await UserService.get_user_movies_language(query.from_user.id)

    # Only do DB lookup if not skipping
    if not skip_db_lookup:
        try:
            async with ClientSession() as session:
                async with session.get(f"https://moviebot.click/downloaded_files/by_tmdb_id", params={"tmdb_id": tmdb_id}) as resp:
                    if resp.status == 200:
                        file = await resp.json()
                        logger.info(f"[User {query.from_user.id}] Found downloaded file for tmdb_id={tmdb_id}, using cached info.")
                        # Render the card using saved info
                        card_data = {
                            "title": file.get("movie_title") or movie.get("title"),
                            "poster": file.get("movie_poster"),
                            "url": file.get("movie_url"),
                            "id": hashlib.sha256(file.get("movie_url").encode()).hexdigest()[:16]
                        }
                        add_wrong_movie_btn = not file.get("checked_by_admin", True)
                        cards = await render_mirror_card_batch([card_data], tmdb_id=tmdb_id, user_lang=user_lang, add_wrong_movie_btn=add_wrong_movie_btn)
                        for msg_text, msg_kb, msg_img, stream_id in cards:
                            if query.message:
                                if msg_img:
                                    msg = await query.message.answer_photo(photo=msg_img, caption=msg_text, reply_markup=msg_kb, parse_mode="HTML")
                                else:
                                    msg = await query.message.answer(text=msg_text, reply_markup=msg_kb, parse_mode="HTML")
                                await store_message_id_in_redis(stream_id, msg.message_id, query.from_user.id)
                        return  # Skip mirror search
        except Exception as e:
            logger.warning(f"[User {query.from_user.id}] Exception while checking downloaded files: {e}")

    # If not found in DB or skipping DB lookup, proceed as before
    try:
        async with ClientSession() as session:
            async with session.post(MIRROR_SEARCH_API_URL, json={
                "query": movie.get('original_title', ''),
                "fallback_query": movie.get('title', ''),
                "lang": user_lang
            }) as resp:
                if resp.status != 200:
                    if query.message:
                        await query.message.answer(gettext(FAILED_TO_SEARCH_MIRRORS_TRY_AGAIN), reply_markup=main_menu_keyboard)
                    logger.error(
                        f"[User {query.from_user.id}] Mirror search failed with status: {resp.status}, body: {await resp.text()}")
                    return
                mirror_results = await resp.json()
    except Exception as e:
        logger.exception(f"[User {query.from_user.id}] Exception during mirror search: {e}\n{traceback.format_exc()}")
        if query.message:
            await query.message.answer(gettext(UNEXPECTED_ERROR_MIRROR_SEARCH_TRY_AGAIN), reply_markup=main_menu_keyboard)
        return

    #check if any of mirrors with results returned have this movie
    if not any(mirror['results'] for mirror in mirror_results):
        if query.message:
            await query.message.answer(gettext(NO_MIRROR_RESULTS_TRY_ANOTHER_MOVIE), reply_markup=main_menu_keyboard)
        return

    # Extract info from backend response
    first_mirror_info = mirror_results[0]
    mirror_name = first_mirror_info.get("mirror")
    geo_priority = first_mirror_info.get("geo_priority")
    results = first_mirror_info.get("results", [])

    logger.info(f"[User {query.from_user.id}] Mirror '{mirror_name}' responded with {len(results)} results (geo={geo_priority})")

    # Store indexed mirror result in the new structure
    mirror_session = MirrorSearchSession(
        user_id=query.from_user.id,
        movie_id=movie_id,  # movie_id is str
        original_query=movie.get('original_title'),
        mirrors_search_results={
            DEFAULT_MIRROR_INDEX: {
                "mirror": mirror_name,
                "geo_priority": geo_priority,
                "results": results
            }
        },
        current_mirror_index=DEFAULT_MIRROR_INDEX,
        current_result_index=0,
        preferred_language=user_lang
    )
    await SessionManager.update_data(query.from_user.id, {"mirror_session": mirror_session.to_dict()})

    # Show top nav first
    top_nav_text, top_nav_keyboard = await get_mirror_navigation_keyboard(mirror_session, position="top", click_source="top")
    if query.message:
        top_panel = await query.message.answer(top_nav_text, reply_markup=top_nav_keyboard)
        top_nav_message_id = top_panel.message_id
    else:
        top_nav_message_id = None

    cards = await render_mirror_card_batch(results[:1], tmdb_id=tmdb_id, user_lang=user_lang)
    card_message_ids = []

    for msg_text, msg_kb, msg_img, stream_id in cards:
        if query.message:
            if msg_img:
                msg = await query.message.answer_photo(photo=msg_img, caption=msg_text, reply_markup=msg_kb, parse_mode="HTML")
            else:
                msg = await query.message.answer(text=msg_text, reply_markup=msg_kb, parse_mode="HTML")
            await store_message_id_in_redis(stream_id, msg.message_id, query.from_user.id)
            card_message_ids.append(msg.message_id)

    bottom_nav_text, bottom_nav_keyboard = await get_mirror_navigation_keyboard(mirror_session, position="bottom", click_source="bottom")
    if query.message:
        bottom_panel = await query.message.answer(bottom_nav_text, reply_markup=bottom_nav_keyboard)
        bottom_nav_message_id = bottom_panel.message_id
    else:
        bottom_nav_message_id = None

    mirror_session.top_nav_message_id = top_nav_message_id
    mirror_session.bottom_nav_message_id = bottom_nav_message_id
    mirror_session.card_message_ids = card_message_ids

    await SessionManager.update_data(query.from_user.id, {"mirror_session": mirror_session.to_dict()})
