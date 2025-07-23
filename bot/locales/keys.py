"""
Translation keys constants for type safety and IDE autocomplete.
This module contains all translation keys used throughout the bot.
"""

# Welcome & Onboarding Messages
WELCOME_MESSAGE = "welcome_message"
ONBOARDING_WELCOME = "onboarding_welcome"
ONBOARDING_BOT_LANG_QUESTION = "onboarding_bot_lang_question"
ONBOARDING_MOVIES_LANG_QUESTION = "onboarding_movies_lang_question"
ONBOARDING_COMPLETED = "onboarding_completed"
ONBOARDING_SKIPPED = "onboarding_skipped"
PREFERENCES_SUGGESTION = "preferences_suggestion"
CUSTOM_NAME_PROMPT = "custom_name_prompt"
BACK_TO_MAIN_MENU = "back_to_main_menu"
GO_BACK_TO_MAIN_MENU = "go_back_to_main_menu"

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
SEARCH_BY_ACTOR_COMING_SOON = "search_by_actor_coming_soon"
SEARCH_BY_DIRECTOR_COMING_SOON = "search_by_director_coming_soon"

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

# Options Menu
OPTIONS_WHAT_TO_CONFIGURE = "options_what_to_configure"
OPTIONS_BOT_LANGUAGE_BTN = "options_bot_language_btn"
OPTIONS_MOVIES_LANGUAGE_BTN = "options_movies_language_btn"
OPTIONS_CHOOSE_BOT_LANGUAGE = "options_choose_bot_language"
OPTIONS_CHOOSE_MOVIES_LANGUAGE = "options_choose_movies_language"
OPTIONS_LANGUAGE_UPDATED = "options_language_updated"

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

# Helper-specific keys
PREFERRED_LANGUAGE_TO_WATCH = "preferred_language_to_watch"
CHANGE_LANGUAGE_BTN = "change_language_btn"
WRONG_MOVIE_BTN = "wrong_movie_btn"
NO_TITLE_FALLBACK = "no_title_fallback"
DEFAULT_OVERVIEW_FALLBACK = "default_overview_fallback"
GOOD_MOVIE_FALLBACK = "good_movie_fallback"
IMDB_RATING_PREFIX = "imdb_rating_prefix"
SELECT_BTN = "select_btn"
COLLAPSE_CARD_BTN = "collapse_card_btn"
EXPAND_CARD_BTN = "expand_card_btn"
SCROLL_DOWN_HINT = "scroll_down_hint"
PRESS_NEXT_HINT = "press_next_hint"
SCROLL_UP_HINT = "scroll_up_hint"
EXPLORING_MOVIES_DEFAULT = "exploring_movies_default"
SHOWING_MOVIES_RANGE = "showing_movies_range"
PREVIOUS_MOVIES_BTN = "previous_movies_btn"
NEXT_MOVIES_BTN = "next_movies_btn"
CAN_NOT_FIND_BTN = "can_not_find_btn"
WATCH_LATER_BTN = "watch_later_btn"

# Keyboard-specific keys
MIRROR_SELECTION_HINT = "mirror_selection_hint"
MIRROR_SELECT_TITLE = "mirror_select_title"
PREVIOUS_BTN = "previous_btn"
NEXT_BTN = "next_btn"
CONFIRM_BTN = "confirm_btn"

# Genre translation keys
GENRE_ACTION = "genre_action"
GENRE_COMEDY = "genre_comedy"
GENRE_ADVENTURE = "genre_adventure"
GENRE_THRILLER = "genre_thriller"
GENRE_ROMANCE = "genre_romance"
GENRE_DRAMA = "genre_drama"
GENRE_FANTASY = "genre_fantasy"
GENRE_MYSTERY = "genre_mystery"
GENRE_FAMILY = "genre_family"
GENRE_ANIMATION = "genre_animation"
GENRE_CRIME = "genre_crime"
GENRE_DOCUMENTARY = "genre_documentary"
GENRE_HISTORY = "genre_history"
GENRE_HORROR = "genre_horror"
GENRE_SCIFI = "genre_scifi"
GENRE_WAR = "genre_war"
GENRE_TV_MOVIE = "genre_tv_movie"
GENRE_MUSIC = "genre_music"

# Search strategy context text keys
SEARCH_CONTEXT_LOOKING_FOR_NAME = "search_context_looking_for_name"
SEARCH_CONTEXT_SEARCHING_BY_GENRE = "search_context_searching_by_genre"
SEARCH_CONTEXT_LOOKING_FOR_GENRES = "search_context_looking_for_genres"

# Utils polling and download messages
POLL_ERROR_OCCURRED_WATCH_AGAIN = "poll_error_occurred_watch_again"
POLL_MOVIE_CONFIG_MISSING = "poll_movie_config_missing"
POLL_STILL_WORKING_WAIT = "poll_still_working_wait"
POLL_TAKING_TOO_LONG_WATCH_AGAIN = "poll_taking_too_long_watch_again"
DOWNLOAD_QUEUE_POSITION = "download_queue_position"
DOWNLOAD_EXTRACTING_DATA = "download_extracting_data"
DOWNLOAD_CONVERTING_VIDEO = "download_converting_video"
DOWNLOAD_UPLOADING_TO_TELEGRAM = "download_uploading_to_telegram"
DOWNLOAD_UPLOADING_PROGRESS = "download_uploading_progress"
DOWNLOAD_PROCESSING_STATUS = "download_processing_status"
DOWNLOAD_FAILED_START_AGAIN = "download_failed_start_again"
DOWNLOAD_TIMEOUT_TRY_LATER = "download_timeout_try_later"

# New key for YouTube downloading status
DOWNLOAD_YOUTUBE_DOWNLOADING = "download_youtube_downloading"

# Direct Download Flow
DOWNLOAD_SOURCE_SELECTION = "download_source_selection"
DOWNLOAD_SOURCE_HDREZKA = "download_source_hdrezka"
DOWNLOAD_SOURCE_YOUTUBE = "download_source_youtube"
DOWNLOAD_SEND_LINK_PROMPT = "download_send_link_prompt"
DOWNLOAD_YOUTUBE_SEND_LINK_PROMPT = "download_youtube_send_link_prompt"
DOWNLOAD_INVALID_LINK = "download_invalid_link"
DOWNLOAD_LINK_PROCESSING = "download_link_processing"
DOWNLOAD_INVALID_YOUTUBE_LINK = "download_invalid_youtube_link"