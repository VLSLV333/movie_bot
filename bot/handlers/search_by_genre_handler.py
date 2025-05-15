from aiogram import Router, types, F
from bot.utils.session_manager import SessionManager
from bot.keyboards.select_movie_genre_keyboard import get_movie_genre_keyboard
from bot.keyboards.select_year_range_keyboard import get_year_range_keyboard
from bot.keyboards.select_year_keyboard import get_select_year_keyboard
from bot.helpers.render_movie_card import render_movie_card
from bot.helpers.render_navigation_panel import render_navigation_panel
from bot.helpers.back_to_main_menu_btn import add_back_to_main_menu_button
from bot.services.tmdb_service import TMDBService
from bot.keyboards.search_type_keyboard import get_search_type_keyboard
from bot.utils.logger import Logger
from bot.search.user_search_context import UserSearchContext
from bot.search.search_strategy import SearchByGenreStrategy

router = Router()
logger = Logger().get_logger()
tmdb_service = TMDBService()

# Entry point for genre search
@router.callback_query(F.data == "search_by_genre")
async def search_by_genre_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    logger.info(f"[User {user_id}] Selected 'Search by Genre'")

    # Clear any existing search state
    await SessionManager.clear_state(user_id)
    await SessionManager.set_state(user_id, "search_by_genre:waiting")
    await SessionManager.update_data(user_id, {"selected_genres": []})

    keyboard = get_movie_genre_keyboard(selected_genres=[])  # initial empty state

    await query.message.edit_text(
        "🎭 Choose one or more genres below\n\nWhen you're ready, press '✅ Confirm':",
        reply_markup=keyboard
    )

    await query.answer()

@router.callback_query(F.data.startswith("toggle_genre:"))
async def toggle_genre_selection(query: types.CallbackQuery):
    user_id = query.from_user.id
    genre_id = int(query.data.split(":")[1])

    session = await SessionManager.get_data(user_id)
    selected = session.get("selected_genres", [])

    if genre_id in selected:
        selected.remove(genre_id)
    else:
        selected.append(genre_id)

    await SessionManager.update_data(user_id, {"selected_genres": selected})

    keyboard = get_movie_genre_keyboard(selected)
    await query.message.edit_reply_markup(reply_markup=keyboard)
    await query.answer()

@router.callback_query(F.data == "confirm_genres")
async def confirm_selected_genres(query: types.CallbackQuery):
    user_id = query.from_user.id
    session = await SessionManager.get_data(user_id)
    selected = session.get("selected_genres", [])

    logger.info(f"[User {user_id}] Confirmed genres: {selected}")
    await SessionManager.set_state(user_id, "search_by_genre:year_range")

    keyboard = get_year_range_keyboard()
    await query.message.edit_text("📅 Now choose a year range:", reply_markup=keyboard)
    await query.answer()

@router.callback_query(F.data.startswith("select_year_range:"))
async def handle_year_range_selection(query: types.CallbackQuery):
    user_id = query.from_user.id
    selected_range = query.data.split(":")[1]  # e.g., "2025-2016"

    logger.info(f"[User {user_id}] Selected year range: {selected_range}")

    start_year, end_year = map(int, selected_range.split("-"))
    year_list = list(range(start_year, end_year - 1, -1))  # descending

    await SessionManager.set_state(user_id, "search_by_genre:years")
    await SessionManager.update_data(user_id, {
        "selected_range": selected_range,
        "year_list": year_list,
        "selected_years": []
    })

    keyboard = get_select_year_keyboard(year_list, selected_years=[])
    await query.message.edit_text(
        "🗓️ Choose year(s). You can tap multiple to select a range:",
        reply_markup=keyboard
    )
    await query.answer()

@router.callback_query(F.data.startswith("select_year:"))
async def toggle_year_selection(query: types.CallbackQuery):
    user_id = query.from_user.id
    selected_year = int(query.data.split(":")[1])

    session = await SessionManager.get_data(user_id)
    selected_years = session.get("selected_years", [])
    year_list = session.get("year_list", [])

    if selected_year in selected_years:
        # If user clicks a year in the range, we treat it as resetting selection to that single year
        selected_years = [selected_year]
    else:
        if len(selected_years) >= 2:
            selected_years = [selected_year]
        else:
            selected_years.append(selected_year)

    selected_years = sorted(set(selected_years), reverse=True)

    await SessionManager.update_data(user_id, {
        "selected_years": selected_years
    })

    keyboard = get_select_year_keyboard(year_list, selected_years)
    await query.message.edit_reply_markup(reply_markup=keyboard)
    await query.answer()

@router.callback_query(F.data == "confirm_years")
async def confirm_selected_years(query: types.CallbackQuery):
    user_id = query.from_user.id
    session = await SessionManager.get_data(user_id)
    selected_years = session.get("selected_years", [])
    selected_genres = session.get("selected_genres", [])

    logger.info(f"[User {user_id}] Confirmed years: {selected_years}")
    logger.info(f"[User {user_id}] Ready to search with genres: {selected_genres} and years: {selected_years}")

    strategy = SearchByGenreStrategy(
        genres=selected_genres,
        years=selected_years,
        language="en-US"  # optional: add lang selection later
    )

    #TODO: what I do not like about this place and this
    #TODO: I am not sure if future context will be avare of fact we have already fetched first results. SO I added current_result_idx=5,current_page=1

    first_page = await strategy.get_movies(tmdb_service, page=1)
    movies = first_page.get("results", [])[:5]

    if not movies:
        keyboard = get_search_type_keyboard()
        await query.message.edit_text(
            "😕 No matches found. Try a new search!",
            reply_markup=keyboard
        )
        await SessionManager.clear_data(user_id)
        await SessionManager.clear_state(user_id)
        await query.answer()
        return

    # TODO: what I do not like about this place and this
    context = UserSearchContext(
        strategy=strategy,
        current_results=first_page.get("results", []),
        total_results=first_page.get("total_results", 0),
        current_result_idx=5,
        current_page=1,
    )

    message_ids = []

    # Top nav
    nav_text_top, nav_keyboard_top = render_navigation_panel(context, position="top")
    nav_keyboard_top = add_back_to_main_menu_button(nav_keyboard_top)
    top_msg = await query.message.answer(nav_text_top, reply_markup=nav_keyboard_top)
    top_id = top_msg.message_id

    for movie in movies:
        text, keyboard, poster = render_movie_card(movie, is_expanded=False)
        msg = await query.message.answer_photo(photo=poster, caption=text, reply_markup=keyboard, parse_mode="HTML")
        message_ids.append(msg.message_id)

    nav_text, nav_keyboard = render_navigation_panel(context, position="bottom")
    nav_keyboard = add_back_to_main_menu_button(nav_keyboard)
    nav_msg = await query.message.answer(nav_text, reply_markup=nav_keyboard)

    await SessionManager.save_context(
        user_id,
        context,
        current_cards_message_ids=message_ids,
        pagination_message_id=nav_msg.message_id,
        top_pagination_message_id=top_id
    )

    await SessionManager.clear_data(user_id)
    await SessionManager.clear_state(user_id)
    await query.answer()

