"""
Translation keys constants for type safety and IDE autocomplete.
This module contains all translation keys used throughout the bot.
"""

# Welcome & Onboarding Messages
WELCOME_MESSAGE = "welcome_message"
ONBOARDING_WELCOME = "onboarding_welcome"
ONBOARDING_NAME_QUESTION = "onboarding_name_question"
ONBOARDING_LANGUAGE_QUESTION = "onboarding_language_question"
ONBOARDING_COMPLETED = "onboarding_completed"
ONBOARDING_SKIPPED = "onboarding_skipped"
PREFERENCES_SUGGESTION = "preferences_suggestion"
CUSTOM_NAME_PROMPT = "custom_name_prompt"
BACK_TO_MAIN_MENU = "back_to_main_menu"

# Main Menu Buttons
FIND_MOVIE_BTN = "find_movie_btn"
RECOMMEND_BTN = "recommend_btn"
DOWNLOAD_BTN = "download_btn"
WATCH_HISTORY_BTN = "watch_history_btn"
FAVORITES_BTN = "favorites_btn"
OPTIONS_BTN = "options_btn"

# Search Interface
SEARCH_TYPE_QUESTION = "search_type_question"
SEARCH_BY_NAME_BTN = "search_by_name_btn"
SEARCH_BY_GENRE_BTN = "search_by_genre_btn"
SEARCH_BY_ACTOR_BTN = "search_by_actor_btn"
SEARCH_BY_DIRECTOR_BTN = "search_by_director_btn"

# Common Buttons
BACK_BTN = "back_btn"
CUSTOM_NAME_BTN = "custom_name_btn"
SET_PREFERENCES_BTN = "set_preferences_btn"
MAYBE_LATER_BTN = "maybe_later_btn"
CONTINUE_BTN = "continue_btn"
CANCEL_BTN = "cancel_btn"

# Status Messages
COMING_SOON = "coming_soon"
FEATURE_UNAVAILABLE = "feature_unavailable"
PROCESSING = "processing"
PLEASE_WAIT = "please_wait"
SUCCESS = "success"
ERROR_OCCURRED = "error_occurred"

# Movie Related
MOVIE_FOUND = "movie_found"
NO_MOVIES_FOUND = "no_movies_found"
MOVIE_DETAILS = "movie_details"
WATCH_MOVIE = "watch_movie"
DOWNLOAD_MOVIE = "download_movie"
ADD_TO_FAVORITES = "add_to_favorites"
REMOVE_FROM_FAVORITES = "remove_from_favorites"

# Language Names (for display in UI)
LANG_ENGLISH = "lang_english"
LANG_UKRAINIAN = "lang_ukrainian"
LANG_RUSSIAN = "lang_russian"

# Notifications
RECOMMENDATIONS_COMING_SOON = "recommendations_coming_soon"
WATCH_HISTORY_COMING_SOON = "watch_history_coming_soon"
FAVORITES_COMING_SOON = "favorites_coming_soon"
OPTIONS_COMING_SOON = "options_coming_soon"
DOWNLOAD_COMING_SOON = "download_coming_soon"

# Error Messages
NETWORK_ERROR = "network_error"
BACKEND_ERROR = "backend_error"
INVALID_INPUT = "invalid_input"
USER_NOT_FOUND = "user_not_found"
PERMISSION_DENIED = "permission_denied"

# Validation Messages
NAME_TOO_LONG = "name_too_long"
NAME_TOO_SHORT = "name_too_short"
INVALID_NAME = "invalid_name"

# Navigation Messages
GENRE_SELECTION_PROMPT = "genre_selection_prompt"
YEAR_RANGE_SELECTION_PROMPT = "year_range_selection_prompt"
YEAR_SELECTION_PROMPT = "year_selection_prompt"

# Fallback Messages
FALLBACK_MENU_PROMPT = "fallback_menu_prompt"

# Language Selection
SELECT_LANGUAGE_FOR_MOVIES = "select_language_for_movies"
LANGUAGE_UPDATED_SUCCESSFULLY = "language_updated_successfully"
ERROR_CANNOT_SHOW_LANGUAGE_OPTIONS = "error_cannot_show_language_options"
ERROR_UPDATE_LANGUAGE_FAILED = "error_update_language_failed"

# Session & Error Messages
SESSION_EXPIRED_RESTART_SEARCH = "session_expired_restart_search"
SOMETHING_WENT_WRONG_TRY_MAIN_MENU = "something_went_wrong_try_main_menu"
SEARCHING_IN_PROGRESS = "searching_in_progress"

# Movie Card Actions
CAST_CREW_COMING_SOON = "cast_crew_coming_soon"
TRAILER_COMING_SOON = "trailer_coming_soon"
RELATED_MOVIES_COMING_SOON = "related_movies_coming_soon"
FAVORITES_STORAGE_COMING_SOON = "favorites_storage_coming_soon"
WATCHLIST_STORAGE_COMING_SOON = "watchlist_storage_coming_soon"
RATINGS_STORAGE_COMING_SOON = "ratings_storage_coming_soon"

# Confirmation & Report Messages
YES_BTN = "yes_btn"
NO_BTN = "no_btn"
CONFIRM_REPORT_MOVIE_NOT_FOUND = "confirm_report_movie_not_found"
REPORT_THANKS_MESSAGE = "report_thanks_message"

# Search Results
SEARCH_BY_NAME_PROMPT = "search_by_name_prompt"
NO_SEARCH_RESULTS_TRY_AGAIN = "no_search_results_try_again"
NO_MATCHES_FOUND_TRY_NEW_SEARCH = "no_matches_found_try_new_search"
NO_MORE_MATCHES_START_NEW_SEARCH = "no_more_matches_start_new_search"

# Mirror Search & Pagination
FAILED_TO_SEARCH_MIRRORS_TRY_AGAIN = "failed_to_search_mirrors_try_again"
UNEXPECTED_ERROR_MIRROR_SEARCH_TRY_AGAIN = "unexpected_error_mirror_search_try_again"
NO_MIRROR_RESULTS_TRY_ANOTHER_MOVIE = "no_mirror_results_try_another_movie"
NO_MORE_MIRROR_RESULTS_TRY_ANOTHER_MOVIE = "no_more_mirror_results_try_another_movie"

# Pagination Messages
WAIT_CARDS_UPDATING = "wait_cards_updating"

# Movie Watching & Download
MOVIE_LINK_NO_LONGER_VALID = "movie_link_no_longer_valid"
LOST_MOVIE_DATA_RESEARCH = "lost_movie_data_research"
PREPARING_MOVIE_DUBS_WATCH = "preparing_movie_dubs_watch"
SORRY_COULDNT_EXTRACT_MOVIE_TRY_AGAIN = "sorry_couldnt_extract_movie_try_again"
START_WATCHING_BTN = "start_watching_btn"
MOVIE_READY_TO_WATCH = "movie_ready_to_watch"
TEXT_DUBS_READY_TO_DOWNLOAD = "text_dubs_ready_to_download"
DOWNLOAD_ANOTHER_DUB = "download_another_dub"
ALREADY_HAVE_MOVIE = "already_have_movie"

# Download Process Messages
CHECKING_DOWNLOADED_VERSIONS_DUBS = "checking_downloaded_versions_dubs"
CHOOSE_DUB_TO_DOWNLOAD = "choose_dub_to_download"
MOVIE_NEVER_DOWNLOADED_BEFORE = "movie_never_downloaded_before"
TRY_SEARCHING_FROM_BEGINNING = "try_searching_from_beginning"
NO_DUBS_AVAILABLE_IN_LANGUAGE = "no_dubs_available_in_language"
DOWNLOAD_DEFAULT_DUB = "download_default_dub"
MOVIE_HAS_ONLY_DEFAULT_DUB = "movie_has_only_default_dub"
ALREADY_AVAILABLE_DUBS = "already_available_dubs"
AVAILABLE_TO_DOWNLOAD = "available_to_download"
CHOOSE_DUB_TO_DOWNLOAD_OR_WATCH = "choose_dub_to_download_or_watch"

# Delivery Bot Messages
MOVIE_READY_TO_WATCH_DELIVERY = "movie_ready_to_watch_delivery"
GET_MOVIE_FROM_DELIVERY_BOT = "get_movie_from_delivery_bot"
MOVIE_READY_START_DELIVERY_BOT = "movie_ready_start_delivery_bot"
OPEN_DELIVERY_BOT = "open_delivery_bot"

# Download Error Messages
DUB_SELECTION_EXPIRED = "dub_selection_expired"
COULD_NOT_PROCESS_DUB_INFO = "could_not_process_dub_info"
ADDED_TO_DOWNLOAD_QUEUE = "added_to_download_queue"
FAILED_TO_TRIGGER_DOWNLOAD = "failed_to_trigger_download"
UNEXPECTED_ERROR_DURING_DOWNLOAD = "unexpected_error_during_download"
DOWNLOAD_LIMIT = "download_limit"
DUPLICATE_DOWNLOAD = "duplicate_download"

END_ONBOARDING_SUCCESS=  "end_onboarding_success"
END_ONBOARDING_FAIL=  "end_onboarding_fail"

ONLY_ONE_DUB='only_one_dub'
NO_DUBS_FOR_LANG='no_dubs_for_lang'
NO_UA_DUBS='no_ua_dubs'