import traceback
import json

from aiogram import Router, types, F
from aiohttp import ClientSession
from bot.utils.session_manager import SessionManager
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

    user_id = query.from_user.id
    movie_id = query.data.split(":", 1)[1]

    movie_json = await redis.get(f"movie_info:{movie_id}")
    movie = json.loads(movie_json)

    tmdb_id = int(movie_id)

    await query.answer("⏳ Searching mirrors...")
    logger.info(f"[User {user_id}] Initiating mirror search for: '{movie.get('title')}'")

    # Retrieve movie title from stored session (you may pass it directly in a real scenario)
    session = await SessionManager.get_user_session(user_id)
    if not session:
        keyboard = get_main_menu_keyboard()
        await query.message.answer(
            "😅 I already forgot what we were searching! Pls start a new search 👇",
            reply_markup=keyboard
        )
        await query.answer()
        return

    # Get user's preferred language from backend
    user_lang = await UserService.get_user_preferred_language(user_id)

    try:
        async with ClientSession() as session:
            logger.debug(
                f"[User {user_id}] Sending mirror search POST to {MIRROR_SEARCH_API_URL} with payload: {{'query': '{movie.get('title')}', 'lang': '{user_lang}'}}")
            async with session.post(MIRROR_SEARCH_API_URL, json={
                "query": movie.get('title'),
                "lang": user_lang
            }) as resp:
                if resp.status != 200:
                    #TODO: provide main menu keyboard, so user doesn't get stuck
                    await query.message.answer("❌ Failed to search mirrors. Try again later.")
                    logger.error(
                        f"[User {user_id}] Mirror search failed with status: {resp.status}, body: {await resp.text()}")
                    return
                mirror_results = await resp.json()
    except Exception as e:
        #TODO: provide main menu keyboard, so user doesn't get stuck
        logger.exception(f"[User {user_id}] Exception during mirror search: {e}\n{traceback.format_exc()}")
        await query.message.answer("❌ Unexpected error during mirror search.")

        return

    if not mirror_results:
        #TODO: provide main menu keyboard, so user doesn't get stuck
        await query.message.answer("😔 No results found on mirror.")
        return

    logger.debug(f"[User {user_id}] Received mirror search results: {[r.get('title') for r in mirror_results]}")

    # Extract info from backend response
    first_mirror_info = mirror_results[0]
    mirror_name = first_mirror_info.get("mirror")
    geo_priority = first_mirror_info.get("geo_priority")
    results = first_mirror_info.get("results", [])

    logger.debug(f"[User {user_id}] Full mirror results:\n{results}")
    logger.info(f"[User {user_id}] Mirror '{mirror_name}' responded with {len(results)} results (geo={geo_priority})")

    # Store indexed mirror result in the new structure
    mirror_session = MirrorSearchSession(
        user_id=user_id,
        movie_id=movie_id,
        original_query=movie.get('title'),
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
    await SessionManager.update_data(user_id, {"mirror_session": mirror_session.to_dict()})

    # Show top nav first
    top_nav_text, top_nav_keyboard = get_mirror_navigation_keyboard(mirror_session, position="top", click_source="top")
    top_panel = await query.message.answer(top_nav_text, reply_markup=top_nav_keyboard)
    top_nav_message_id = top_panel.message_id

    cards = await render_mirror_card_batch(results[:1], tmdb_id=tmdb_id, user_lang=user_lang)
    card_message_ids = []

    for msg_text, msg_kb, msg_img, stream_id in cards:
        if msg_img:
            msg = await query.message.answer_photo(photo=msg_img, caption=msg_text, reply_markup=msg_kb, parse_mode="HTML")
        else:
            msg = await query.message.answer(text=msg_text, reply_markup=msg_kb, parse_mode="HTML")
        
        # Store message ID in Redis for later retrieval when updating the card
        await store_message_id_in_redis(stream_id, msg.message_id, user_id)

        card_message_ids.append(msg.message_id)

    bottom_nav_text, bottom_nav_keyboard = get_mirror_navigation_keyboard(mirror_session, position="bottom", click_source="bottom")
    bottom_panel = await query.message.answer(bottom_nav_text, reply_markup=bottom_nav_keyboard)
    bottom_nav_message_id = bottom_panel.message_id

    mirror_session.top_nav_message_id = top_nav_message_id
    mirror_session.bottom_nav_message_id = bottom_nav_message_id
    mirror_session.card_message_ids = card_message_ids

    await SessionManager.update_data(user_id, {"mirror_session": mirror_session.to_dict()})
