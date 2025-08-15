import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.hdrezka.hdrezka_extract_to_download import extract_to_download_with_recovery
from backend.video_redirector.hdrezka.hdrezka_merge_ts_into_mp4 import merge_ts_to_mp4
from backend.video_redirector.utils.upload_video_to_tg import check_size_upload_large_file
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.utils.redis_client import RedisClient
from typing import Optional

logger = logging.getLogger(__name__)

def load_delivery_bots_config() -> list:
    """
    Load delivery bot configuration from delivery_bots.json file.
    Returns: List of dictionaries with 'username' and 'token' keys
    """
    config_file = os.path.join(os.path.dirname(__file__), "..", "utils", "delivery_bots.json")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            bots_config = json.load(f)
        
        # Validate structure
        if not isinstance(bots_config, list):
            raise ValueError("delivery_bots.json must contain a JSON array")
        
        for i, bot in enumerate(bots_config):
            if not isinstance(bot, dict) or "username" not in bot or "token" not in bot:
                raise ValueError(f"Invalid bot configuration at index {i}: {bot}")
            if not bot["username"] or not bot["token"]:
                raise ValueError(f"Empty username or token at index {i}: {bot}")
        
        logger.info(f"✅ Loaded {len(bots_config)} delivery bot(s) from {config_file}")
        for i, bot in enumerate(bots_config):
            logger.info(f"   Bot {i+1}: {bot['username']}")
        
        return bots_config
        
    except FileNotFoundError:
        logger.error(f"❌ Delivery bots configuration file not found: {config_file}")
        raise ValueError(f"delivery_bots.json file not found at {config_file}")
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON in delivery_bots.json: {e}")
        raise ValueError(f"Invalid JSON format in delivery_bots.json: {e}")
    except Exception as e:
        logger.error(f"❌ Error loading delivery bots configuration: {e}")
        raise

async def handle_download_task(task_id: str, movie_url: str, tmdb_id: int, lang: str, dub: str, movie_title: str, movie_poster: str):
    redis = RedisClient.get_client()
    await redis.set(f"download:{task_id}:status", "extracting", ex=3600)

    # Remove from user's active downloads set when done (success or error)
    tg_user_id = None
    try:
        result = await extract_to_download_with_recovery(url=movie_url, selected_dub=dub, lang=lang)
        if not result:
            raise Exception("No playable stream found for selected dub. Or probably something went wrong")

        await redis.set(f"download:{task_id}:status", "merging", ex=3600)
        
        try:
            output_files = await merge_ts_to_mp4(task_id, result["url"], result['headers'])
        except Exception as e:
            # Handle any other merge-related errors
            logger.error(f"[Download Task {task_id}] Unexpected merge error: {e}")
            raise Exception(f"Unexpected error during video merge: {str(e)}")

        if not output_files:
            raise Exception("Failed to merge video segments into MP4 files - no output generated")

        await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
        try:
            upload_results = await process_parallel_uploads(output_files, task_id)
        except Exception as e:
            raise Exception(f"Upload failed: {str(e)}")

        consolidated_result = await consolidate_upload_results(upload_results, task_id)

        if not consolidated_result:
            raise Exception("Failed to consolidate upload results.")

        tg_bot_token_file_owner = consolidated_result["bot_token"]
        parts = consolidated_result["parts"]
        session_name = consolidated_result["session_name"]

        # Save in DB
        async with get_db() as session:
            # Sanitize before persisting to DB for consistent keying
            from backend.video_redirector.utils.hdrezka_url import sanitize_hdrezka_url
            db_entry = DownloadedFile(
                tmdb_id=tmdb_id,
                lang=lang,
                dub=dub,
                quality=result["quality"],
                tg_bot_token_file_owner=tg_bot_token_file_owner,
                created_at=datetime.now(timezone.utc),
                movie_title=movie_title,
                movie_poster=movie_poster,
                movie_url=sanitize_hdrezka_url(movie_url) if movie_url else None,
                session_name=session_name
            )
            session.add(db_entry)
            await session.flush()  # Get db_entry.id

            db_id_to_get_parts = db_entry.id

            for part in parts:
                session.add(DownloadedFilePart(
                    downloaded_file_id=db_entry.id,
                    part_number=part["part"],
                    telegram_file_id=part["file_id"]
                ))
            await session.commit()

        await redis.set(f"download:{task_id}:status", "done", ex=3600)

        # Success cleanup: remove all merged MP4 output files and the downloads/<task_id> parts folder if any
        try:
            for path in output_files or []:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                        logger.debug(f"[{task_id}] Cleaned merged output: {path}")
                except Exception as _e:
                    logger.warning(f"[{task_id}] Couldn't remove merged output {path}: {_e}")
            # Best-effort cleanup of downloads/parts for this task if present
            try:
                parts_dir = os.path.join(os.path.dirname(__file__), "..", "utils", "downloads", "parts")
                parts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads", "parts"))
                # Remove any files for this task_id
                if os.path.exists(parts_dir):
                    for fname in os.listdir(parts_dir):
                        if task_id in fname:
                            fpath = os.path.join(parts_dir, fname)
                            if os.path.isfile(fpath):
                                try:
                                    os.remove(fpath)
                                except Exception:
                                    pass
            except Exception:
                pass
        except Exception:
            pass

        if len(parts) == 1:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "tg_bot_token_file_owner": tg_bot_token_file_owner,
                "telegram_file_id": parts[0]["file_id"]
            }), ex=86400)
        else:
            await redis.set(f"download:{task_id}:result", json.dumps({
                "db_id_to_get_parts": db_id_to_get_parts,
            }), ex=86400)
    except Exception as e:
        logger.error(f"[Download Task {task_id}] Failed Exception: {e}")
        await redis.set(f"download:{task_id}:status", "error", ex=3600)
        await redis.set(f"download:{task_id}:error", str(e), ex=3600)
        await notify_admin(f"[Download Task {task_id}] Failed: {e}")
    finally:
        # Remove from user's active downloads set
        if tg_user_id is None:
            # Try to get from Redis
            tg_user_id = await redis.get(f"download:{task_id}:user_id")
        if tg_user_id:
            await redis.srem(f"active_downloads:{tg_user_id}", task_id)  # type: ignore

        # Failure cleanup (if we raised earlier): ensure output_files are deleted
        try:
            if 'output_files' in locals() and output_files:
                for path in output_files:
                    try:
                        if path and os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        pass
        except Exception:
            pass

async def process_parallel_uploads(output_files: list, task_id: str) -> list:
    """
    Process multiple MP4 files in parallel using check_size_upload_large_file()
    with bot rotation logic - all parts use the same bot for consistency.
    
    Returns: List of upload results for each file
    Raises: Exception if ALL bots fail (all-or-nothing approach)
    """
    logger.info(f"🚀 [{task_id}] Starting parallel upload of {len(output_files)} files with bot rotation")
    
    # Load available bots
    try:
        available_bots = load_delivery_bots_config()
        if not available_bots:
            raise Exception("No delivery bots configured")
    except Exception as e:
        logger.error(f"❌ [{task_id}] Failed to load delivery bots configuration: {e}")
        raise Exception(f"Failed to load delivery bots configuration: {e}")
    
    # Try each bot until one succeeds for all files
    for bot_index, bot_config in enumerate(available_bots):
        bot_username = bot_config["username"]
        
        logger.info(f"🔄 [{task_id}] Trying bot {bot_index + 1}/{len(available_bots)}: {bot_username}")
        
        try:
            upload_tasks = []
            for i, file_path in enumerate(output_files):
                # Create unique task ID for each file
                file_task_id = f"{task_id}_file{i+1}"
                
                # Create task with individual error handling and its own database session
                async def upload_single_file(file_path, file_task_id, file_index, bot_info):
                    try:
                        # Each task gets its own database session
                        async with get_db() as db:
                            result = await check_size_upload_large_file(file_path, file_task_id, db, bot_info)
                        
                        return {
                            "file_index": file_index,
                            "file_path": file_path,
                            "result": result,
                            "success": True
                        }
                    except Exception as e:
                        logger.error(f"❌ [{task_id}] File {file_index+1} upload exception with bot {bot_username}: {e}")
                        return {
                            "file_index": file_index,
                            "file_path": file_path,
                            "result": None,
                            "success": False,
                            "error": str(e)
                        }
                
                task = asyncio.create_task(
                    upload_single_file(file_path, file_task_id, i, bot_config)
                )
                upload_tasks.append(task)
            
            # Wait for ALL uploads to complete simultaneously with this bot
            logger.info(f"⏳ [{task_id}] Waiting for {len(upload_tasks)} parallel uploads with bot {bot_username}...")
            
            results = await asyncio.gather(*upload_tasks)
            
            # Check if ALL uploads succeeded with this bot
            successful_results = [r for r in results if r["success"]]
            failed_results = [r for r in results if not r["success"]]
            
            if failed_results:
                # At least one upload failed with this bot - try next bot
                failed_files = [f"File {r['file_index']+1}" for r in failed_results]
                logger.warning(f"⚠️ [{task_id}] Bot {bot_username} failed for {len(failed_results)} files: {failed_files}")
                
                # If this was the last bot, raise exception
                if bot_index == len(available_bots) - 1:
                    raise Exception(f"All {len(available_bots)} bots failed. "
                                  f"Last bot {bot_username} failed for {len(failed_results)}/{len(output_files)} files. "
                                  f"Failed files: {', '.join(failed_files)}")
                
                # Try next bot
                continue
            
            # All uploads succeeded with this bot!
            logger.info(f"✅ [{task_id}] Bot {bot_username} successfully uploaded all {len(successful_results)} files!")
            
            return successful_results
            
        except Exception as e:
            logger.error(f"❌ [{task_id}] Bot {bot_username} failed completely: {e}")
            
            # If this was the last bot, raise exception
            if bot_index == len(available_bots) - 1:
                raise Exception(f"All {len(available_bots)} bots failed. "
                              f"Last bot {bot_username} error: {e}")
            
            # Try next bot
            continue
        
    # This should never be reached due to the exception handling above
    raise Exception(f"Unexpected: All {len(available_bots)} bots failed without proper error handling")

async def consolidate_upload_results(upload_results: list, task_id: str) -> Optional[dict]:
    """
    Consolidate results from parallel uploads into a single result structure
    """
    if not upload_results:
        logger.error(f"❌ [{task_id}] No successful uploads to consolidate")
        return None
    
    # Use the first successful upload's bot token and session
    first_result = upload_results[0]["result"]
    consolidated_parts = []

    # Combine all parts from all files
    part_mapping = {}
    for upload_result in upload_results:
        part_num = list(upload_result["result"]["parts"].keys())[0]
        part_mapping[part_num] = upload_result["result"]["parts"][part_num]

    logger.info(f"📋 [{task_id}] Found parts: {sorted(part_mapping.keys())}")

    for part_num in sorted(part_mapping.keys()):
        pieces_of_this_part = part_mapping[part_num]

        logger.info(f"📋 [{task_id}] Processing part {part_num} with {len(pieces_of_this_part)} pieces")

        correct_db_input_num = 0
        # Add each piece from this part to consolidated_parts
        if len(pieces_of_this_part) >= 2:
            correct_db_input_num = part_num**2

        for piece in pieces_of_this_part:
            consolidated_parts.append({
                "part": piece["part"] + part_num + correct_db_input_num,
                "file_id": piece["file_id"]
            })

    logger.info(f"📋 [{task_id}] Consolidated {len(consolidated_parts)} parts from {len(upload_results)} files")
    
    return {
        "bot_token": first_result["bot_token"],
        "parts": consolidated_parts,
        "session_name": first_result["session_name"] #actually all parts are uploaded by different sessions, so this only shows session name of first result
    }
