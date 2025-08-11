import asyncio
import json
import logging
import os
import subprocess
import shutil
from datetime import datetime, timezone
from typing import Optional
from backend.video_redirector.db.models import DownloadedFile, DownloadedFilePart
from backend.video_redirector.db.session import get_db
from backend.video_redirector.db.crud_downloads import get_file_id
from backend.video_redirector.hdrezka.hdrezka_download_executor import (
    process_parallel_uploads,
    consolidate_upload_results,
)
from backend.video_redirector.utils.notify_admin import notify_admin
from backend.video_redirector.utils.redis_client import RedisClient
import re

logger = logging.getLogger(__name__)

# Preferred YouTube player clients in order
# Prioritize clients that often expose full DASH without SABR/PO token issues
PREFERRED_YT_CLIENTS = ["ios", "tv", "mweb", "web", "android"]

# Base download directory - each task gets its own subdirectory to avoid collisions
BASE_DOWNLOAD_DIR = "downloads"
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

def get_task_download_dir(task_id: str) -> str:
    """
    Create a unique download directory for this task using the task_id directly
    to avoid collisions and ensure accurate progress tracking.
    """
    task_dir = os.path.join(BASE_DOWNLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    return task_dir

async def debug_available_formats(video_url: str, task_id: str, client_name: str, use_cookies: bool = False):
    """Run a formats debug for a specific client and log top video-only heights.

    This logs a compact per-client summary to help see where HQ is available.
    """
    try:
        logger.debug(f"[{task_id}] 🔍 Debug: Getting all available formats for client={client_name}...")
        
        cmd = [
            "yt-dlp",
            "--ignore-config",
            "--list-formats",
            "--no-playlist",
            "--no-warnings",
            "--extractor-args", f"youtube:player_client={client_name}",
        ]
        if use_cookies:
            cmd += ["--cookies", "cookies.txt"]
        cmd += [video_url]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            
            # Log full format table for debugging (full dump for auditing)
            logger.debug(f"[{task_id}] 🔍 Debug: FULL format list ({len(lines)} lines) for {client_name}:")
            for i, line in enumerate(lines):
                logger.debug(f"[{task_id}] 🔍 {client_name} {i+1:3d}: {line}")
            
            # Parse and summarize heights
            video_only_heights = []
            combined_heights = []
            audio_count = 0
            for line in lines:
                ll = line.lower()
                parts = line.split()
                if len(parts) < 3:
                    continue
                resolution = parts[2]
                if 'audio only' in ll or resolution == 'audio':
                    audio_count += 1
                    continue
                if 'x' in resolution:
                    try:
                        width, height = resolution.split('x')
                        height_val = int(height)
                        if 'video only' in ll:
                            video_only_heights.append(height_val)
                        else:
                            combined_heights.append(height_val)
                    except Exception:
                        continue

            video_only_heights.sort(reverse=True)
            combined_heights.sort(reverse=True)
            top_vo = video_only_heights[:5]
            top_co = combined_heights[:5]
            logger.info(
                f"[{task_id}] 🔍 {client_name} summary: VO_max={top_vo[0] if top_vo else 0} CO_max={top_co[0] if top_co else 0} "
                f"VO_top={top_vo} CO_top={top_co} audio_only_count={audio_count}"
            )
        else:
            logger.warning(f"[{task_id}] 🔍 Debug: Failed to get formats: {result.stderr}")
            
    except Exception as e:
        logger.warning(f"[{task_id}] 🔍 Debug: Error getting formats: {e}")

async def get_best_format_id(video_url: str, target_quality: str, task_id: str, use_cookies: bool = False) -> Optional[tuple]:
    """Get best format selection and chosen player client.

    Returns tuple: (format_selector, can_copy, estimated_size, chosen_client)
    or None if nothing works across all clients.
    """

    # Per-client diagnostics will run inside the loop

    sabr_markers = [
        "YouTube is forcing SABR streaming",
        "missing a url",
    ]

    sabr_blocked_on_web = False
    candidates = []  # each: {fmt, can_copy, est_size, client, height, source}
    target_height = int(target_quality.replace('p', ''))

    best_overall = None  # track best candidate so far
    for client_name in PREFERRED_YT_CLIENTS:
        logger.info(f"[{task_id}] Trying player_client={client_name}")

        # Per-client diagnostics: list formats and log top heights
        try:
            await debug_available_formats(video_url, task_id, client_name, use_cookies=use_cookies)
        except Exception:
            pass

        # Strategy 1: JSON dump
        try:
            cmd = [
                "yt-dlp",
                "--ignore-config",
                "--dump-json",
                "--no-playlist",
                "--no-warnings",
                "--retries", "3",
                "--retry-sleep", "2",
                "--sleep-requests", "0.5",
                "--extractor-args", f"youtube:player_client={client_name}",
            ]
            if use_cookies:
                cmd += ["--cookies", "cookies.txt"]
            cmd += [video_url]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if "Failed to extract any player response" in result.stderr:
                logger.error(f"[{task_id}] 🛑UPDATE YT-DLP EMMERGENCY🛑: {result.stderr}")
                await notify_admin(f"🛑UPDATE YT-DLP EMMERGENCY🛑\nTask: {task_id}\n{result.stderr}")
                raise Exception("do not retry")

            if client_name == "web" and any(m in result.stderr for m in sabr_markers):
                logger.warning(f"[{task_id}] web client SABR detected, skipping to next client")
                sabr_blocked_on_web = True
                # Do not return; try next client
            elif result.returncode == 0:
                try:
                    video_info = json.loads(result.stdout)
                    video_duration = video_info.get("duration", 0)
                    formats = video_info.get("formats", [])
                    # Dump raw JSON for auditing
                    try:
                        logger.info(f"[{task_id}] 🔍 {client_name} JSON RAW: {result.stdout[:5000]}...")
                    except Exception:
                        pass
                    if formats:
                        logger.info(f"[{task_id}] Found {len(formats)} formats via JSON method ({client_name})")
                        # Heuristic: detect suspiciously low max height on web
                        if client_name == "web":
                            max_combined_height = 0
                            try:
                                for f in formats:
                                    if f.get('vcodec') not in (None, 'none') and f.get('acodec') not in (None, 'none') and f.get('height'):
                                        max_combined_height = max(max_combined_height, int(f.get('height') or 0))
                            except Exception:
                                pass
                            if len(formats) < 10 or (max_combined_height and max_combined_height < max(720, int(target_height*0.8))):
                                logger.info(f"[{task_id}] Heuristic: WEB looks SABR-limited (formats={len(formats)}, max_combined_height={max_combined_height})")
                                sabr_blocked_on_web = True

                        json_result = await _analyze_formats_from_json(formats, target_quality, task_id, video_duration)
                        if json_result:
                            # Support optional meta in 4th element
                            fmt = json_result[0]
                            can_copy = json_result[1]
                            estimated_size = json_result[2]
                            meta = json_result[3] if len(json_result) >= 4 and isinstance(json_result[3], dict) else {}
                            height_meta = int(meta.get('height') or 0) if meta else 0
                            # If height unknown, try find from formats
                            if not height_meta:
                                try:
                                    for f in formats:
                                        if f.get('format_id') == fmt and f.get('height'):
                                            height_meta = int(f.get('height'))
                                            break
                                except Exception:
                                    height_meta = 0
                            # If JSON gave us ids, probe sizes quickly to improve estimate
                            if meta:
                                try:
                                    probed_total = 0
                                    v_id = meta.get('video_id')
                                    a_id = meta.get('audio_id')
                                    if v_id and "+" not in str(v_id):
                                        v_probe = subprocess.run([
                                            "yt-dlp","--ignore-config","-f", str(v_id),"--no-download","--print","%(filesize|filesize_approx)s",
                                            "--extractor-args", f"youtube:player_client={client_name}", video_url
                                        ], capture_output=True, text=True, timeout=7)
                                        if v_probe.returncode == 0:
                                            v_sz = (v_probe.stdout or '').strip().splitlines()[-1].strip()
                                            if v_sz.isdigit():
                                                probed_total += int(v_sz)
                                    if a_id:
                                        a_probe = subprocess.run([
                                            "yt-dlp","--ignore-config","-f", str(a_id),"--no-download","--print","%(filesize|filesize_approx)s",
                                            "--extractor-args", f"youtube:player_client={client_name}", video_url
                                        ], capture_output=True, text=True, timeout=7)
                                        if a_probe.returncode == 0:
                                            a_sz = (a_probe.stdout or '').strip().splitlines()[-1].strip()
                                            if a_sz.isdigit():
                                                probed_total += int(a_sz)
                                    if probed_total > 0:
                                        estimated_size = probed_total
                                except Exception as e:
                                    logger.debug(f"[{task_id}] JSON size probe failed: {e}")
                            candidates.append({
                                'fmt': fmt,
                                'can_copy': can_copy,
                                'est_size': estimated_size,
                                'client': client_name,
                                'height': height_meta or 0,
                                'source': 'JSON'
                            })
                            logger.info(f"[{task_id}] ✅ Candidate via JSON | client={client_name} f='{fmt}' can_copy={can_copy} est_size={estimated_size} height={height_meta}")
                            # Early exit: if good enough (copy and height >= target), stop searching
                            if can_copy and height_meta and height_meta >= target_height:
                                best = {'fmt': fmt, 'can_copy': can_copy, 'est_size': estimated_size, 'client': client_name, 'height': height_meta, 'source': 'JSON'}
                                logger.info(f"[{task_id}] 🛑 Early exit on client={client_name} with good candidate: {best}")
                                return (fmt, can_copy, estimated_size, client_name)
                        else:
                            # Dump quick table of a few formats for visibility
                            try:
                                preview = []
                                for f in formats[:10]:
                                    preview.append(
                                        f"id={f.get('format_id')} ext={f.get('ext')} v={f.get('vcodec')} a={f.get('acodec')} "
                                        f"res={f.get('width')}x{f.get('height')} tbr={f.get('tbr')} size={f.get('filesize') or f.get('filesize_approx')}"
                                    )
                                logger.info(f"[{task_id}] JSON preview (top 10): " + " | ".join(preview))
                            except Exception:
                                pass
                    else:
                        logger.warning(f"[{task_id}] No formats in JSON response ({client_name})")
                except json.JSONDecodeError as e:
                    logger.warning(f"[{task_id}] Failed to parse JSON ({client_name}): {e}")
            else:
                logger.warning(f"[{task_id}] JSON method failed ({client_name}): {result.stderr}")
        except Exception as e:
            logger.warning(f"[{task_id}] JSON format detection failed ({client_name}): {e}")

        # Strategy 2: list-formats parsing
        try:
            logger.info(f"[{task_id}] Text parsing method... ({client_name})")
            cmd = [
                "yt-dlp",
                "--ignore-config",
                "--list-formats",
                "--no-playlist",
                "--no-warnings",
                "--retries", "3",
                "--retry-sleep", "2",
                "--sleep-requests", "0.5",
                "--extractor-args", f"youtube:player_client={client_name}",
            ]
            if use_cookies:
                cmd += ["--cookies", "cookies.txt"]
            cmd += [video_url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

            if "Failed to extract any player response" in result.stderr:
                logger.error(f"[{task_id}] 🛑UPDATE YT-DLP EMMERGENCY🛑: {result.stderr}")
                await notify_admin(f"🛑UPDATE YT-DLP EMMERGENCY🛑\nTask: {task_id}\n{result.stderr}")
                raise Exception("do not retry")

            if client_name == "web" and any(m in result.stderr for m in sabr_markers):
                logger.warning(f"[{task_id}] web client SABR detected (text), skipping to next client")
                sabr_blocked_on_web = True
            elif result.returncode == 0:
                # Skip TEXT if JSON already yielded good enough candidate in this client
                skip_text = False
                if candidates:
                    last = candidates[-1]
                    if last['client'] == client_name and last['source'] == 'JSON' and last['can_copy'] and last['height'] and last['height'] >= target_height:
                        skip_text = True
                if skip_text:
                    logger.info(f"[{task_id}] Skipping TEXT parsing for {client_name} due to solid JSON result")
                else:
                    text_result = await _analyze_formats_from_text(result.stdout, target_quality, task_id, known_duration=locals().get('video_duration', 0) or 0)
                    if text_result:
                        fmt = text_result[0]
                        can_copy = text_result[1]
                        estimated_size = text_result[2]
                        height_meta = 0
                        meta = text_result[3] if len(text_result) >= 4 and isinstance(text_result[3], dict) else {}
                        if meta:
                            height_meta = int(meta.get('height') or 0)
                        candidates.append({
                            'fmt': fmt,
                            'can_copy': can_copy,
                            'est_size': estimated_size,
                            'client': client_name,
                            'height': height_meta,
                            'source': 'TEXT'
                        })
                        # Early exit on good TEXT result
                        if can_copy and height_meta and height_meta >= target_height:
                            logger.info(f"[{task_id}] 🛑 Early exit on TEXT client={client_name} with good candidate height={height_meta}")
                            return (fmt, can_copy, estimated_size, client_name)
                        logger.info(f"[{task_id}] ✅ Candidate via TEXT | client={client_name} f='{fmt}' can_copy={can_copy} est_size={estimated_size} height={height_meta}")
                    # If text_result did not contain a solid size, try probing sizes quickly
                    if (meta and not estimated_size):
                        v_id = meta.get('video_id')
                        a_id = meta.get('audio_id')
                        probed_total = 0
                        try:
                            if v_id:
                                v_probe = subprocess.run([
                                    "yt-dlp","--ignore-config","-f", str(v_id),"--no-download","--print","%(filesize|filesize_approx)s",
                                    "--extractor-args", f"youtube:player_client={client_name}", video_url
                                ], capture_output=True, text=True, timeout=7)
                                if v_probe.returncode == 0:
                                    v_sz = (v_probe.stdout or '').strip().splitlines()[-1].strip()
                                    if v_sz.isdigit():
                                        probed_total += int(v_sz)
                            if a_id:
                                a_probe = subprocess.run([
                                    "yt-dlp","--ignore-config","-f", str(a_id),"--no-download","--print","%(filesize|filesize_approx)s",
                                    "--extractor-args", f"youtube:player_client={client_name}", video_url
                                ], capture_output=True, text=True, timeout=7)
                                if a_probe.returncode == 0:
                                    a_sz = (a_probe.stdout or '').strip().splitlines()[-1].strip()
                                    if a_sz.isdigit():
                                        probed_total += int(a_sz)
                        except Exception as e:
                            logger.debug(f"[{task_id}] Size probe failed: {e}")
                        if probed_total > 0:
                            estimated_size = probed_total
                            candidates[-1]['est_size'] = estimated_size
                            logger.info(f"[{task_id}] 🔍 Probed TEXT merge size: {estimated_size} bytes")
                        else:
                            # As last resort, probe duration and estimate via tbr/abr already parsed inside analyzer
                            try:
                                dur_probe = subprocess.run([
                                    "yt-dlp","--ignore-config","--no-download","--print","%(duration)s",
                                    "--extractor-args", f"youtube:player_client={client_name}", video_url
                                ], capture_output=True, text=True, timeout=5)
                                if dur_probe.returncode == 0:
                                    dur_str = (dur_probe.stdout or '').strip().splitlines()[-1].strip()
                                    if dur_str and dur_str.replace('.', '', 1).isdigit():
                                        # If we have duration but no sizes, fallback to 1GB placeholder to keep progress watcher conservative
                                        estimated_size = max(estimated_size, 1_000_000_000)
                                        candidates[-1]['est_size'] = estimated_size
                            except Exception:
                                pass
            else:
                logger.warning(f"[{task_id}] Text method failed ({client_name}): {result.stderr}")
        except Exception as e:
            logger.warning(f"[{task_id}] Text format detection failed ({client_name}): {e}")

        # Strategy 3: Selector-based fallback (avoid -f best)
        # Skip fallbacks if we already have a good candidate (copy and height>=target)
        have_good = any(c['can_copy'] and c['height'] and c['height'] >= target_height for c in candidates if c['client'] == client_name)
        if have_good:
            logger.info(f"[{task_id}] Skipping FALLBACK for {client_name} due to existing good candidate")
            continue
        logger.warning(f"[{task_id}] Using format selectors as fallback ({client_name})")
        fallback_formats = [
            ("bestvideo*[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]", True),
            ("bestvideo*[height<=1080]+bestaudio/best[height<=1080]", False),
        ]

        for format_selector, can_copy in fallback_formats:
            try:
                test_cmd = [
                    "yt-dlp",
                    "--ignore-config",
                    "-f", format_selector,
                    "--no-download",
                    "--no-playlist",
                    "--quiet",
                    "--retries", "3",
                    "--retry-sleep", "2",
                    "--sleep-requests", "0.5",
                    "--extractor-args", f"youtube:player_client={client_name}",
                    video_url,
                ]
                test_result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=15)
                if client_name == "web" and any(m in (test_result.stderr or "") for m in sabr_markers):
                    logger.warning(f"[{task_id}] web client SABR detected (probe), skipping to next client")
                    break
                if test_result.returncode == 0:
                    logger.info(f"[{task_id}] Using fallback format: {format_selector} ({client_name})")
                    # Better size estimation for fallback: try to probe
                    estimated_size = 700_000_000
                    try:
                        probe_cmd = [
                            "yt-dlp", "--ignore-config",
                            "-f", format_selector,
                            "--no-download",
                            "--print", "%(filesize_approx|filesize)s",
                            "--extractor-args", f"youtube:player_client={client_name}",
                            video_url
                        ]
                        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=20)
                        if probe_res.returncode == 0:
                            size_str = (probe_res.stdout or "").strip().splitlines()[-1].strip()
                            if size_str.isdigit():
                                estimated_size = int(size_str)
                                logger.info(f"[{task_id}] Fallback size probe: {estimated_size} bytes")
                    except Exception as e:
                        logger.debug(f"[{task_id}] Fallback size probe failed: {e}")

                    # Probe height for ranking (avoid assuming target height)
                    height_probe = 0
                    try:
                        height_cmd = [
                            "yt-dlp", "--ignore-config",
                            "-f", format_selector,
                            "--no-download",
                            "--print", "%(height|resolution)s",
                            "--extractor-args", f"youtube:player_client={client_name}",
                            video_url
                        ]
                        height_res = subprocess.run(height_cmd, capture_output=True, text=True, timeout=20)
                        if height_res.returncode == 0:
                            raw_val = (height_res.stdout or "").strip().splitlines()[-1].strip()
                            # raw_val can be "1080" or "1920x1080"; parse safely
                            if "x" in raw_val:
                                try:
                                    height_probe = int(raw_val.split("x")[-1])
                                except Exception:
                                    height_probe = 0
                            elif raw_val.isdigit():
                                height_probe = int(raw_val)
                    except Exception as e:
                        logger.debug(f"[{task_id}] Fallback height probe failed: {e}")

                    candidates.append({
                        'fmt': format_selector,
                        'can_copy': can_copy,
                        'est_size': estimated_size,
                        'client': client_name,
                        'height': height_probe or max(0, int(target_height // 3)),
                        'source': 'FALLBACK'
                    })
                    logger.info(f"[{task_id}] ✅ Candidate via FALLBACK | client={client_name} selector='{format_selector}' can_copy={can_copy} est_size={estimated_size} height={height_probe or 'unknown'}")
            except Exception as e:
                logger.debug(f"[{task_id}] Format {format_selector} test failed ({client_name}): {e}")
                continue

    # Final cross-client selection: pick highest height, prefer JSON/TEXT over FALLBACK, prefer MP4 copyable
    if candidates:
        def rank(c):
            source_rank = {'JSON': 2, 'TEXT': 1, 'FALLBACK': 0}.get(c['source'], 0)
            can_copy_rank = 1 if c['can_copy'] else 0
            return (c['height'], source_rank, can_copy_rank)

        best = sorted(candidates, key=rank, reverse=True)[0]
        logger.info(f"[{task_id}] 🏆 Cross-client best candidate | client={best['client']} src={best['source']} height={best['height']} f='{best['fmt']}' can_copy={best['can_copy']} est_size={best['est_size']}")
        return (best['fmt'], best['can_copy'], best['est_size'], best['client'])

    if sabr_blocked_on_web:
        logger.error(f"[{task_id}] All format detection methods failed; SABR blocked on web client and no suitable formats via android/tv")
        raise Exception("SABR blocked on all clients")
    else:
        logger.error(f"[{task_id}] All format detection methods failed across clients: {PREFERRED_YT_CLIENTS}")
        return None

async def _analyze_formats_from_json(formats: list, target_quality: str, task_id: str, video_duration: float = 0) -> Optional[tuple]:
    """Analyze formats from JSON data with original audio preference and return estimated size"""
    video_only_formats = []
    audio_only_formats = []  
    combined_formats = []
    target_height = int(target_quality.replace('p', ''))
    for fmt in formats:
        format_id = fmt.get('format_id')
        ext = fmt.get('ext', 'unknown')
        vcodec = fmt.get('vcodec', 'none')
        acodec = fmt.get('acodec', 'none')
        width = fmt.get('width')
        height = fmt.get('height')
        language = fmt.get('language', 'unknown')
        language_preference = fmt.get('language_preference', -1)
        filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
        if not format_id:
            continue
        # Audio-only: be more tolerant detecting audio tracks
        if vcodec == 'none' and (
            acodec not in (None, 'none') or
            ext in ['m4a', 'mp4'] or
            fmt.get('abr') is not None or
            str(format_id) in {'139', '140', '141'}
        ):
            is_original = (
                language_preference == 10 or
                language in ['original', 'default', 'primary'] or
                'original' in str(fmt).lower()
            )
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'acodec': acodec,
                'abr': fmt.get('abr', 0),
                'language': language,
                'language_preference': language_preference,
                'is_original': is_original,
                'filesize': filesize
            })
        elif vcodec != 'none' and acodec == 'none' and width and height:
            video_only_formats.append({
                'id': format_id,
                'ext': ext,
                'vcodec': vcodec,
                'width': width,
                'height': height,
                'tbr': fmt.get('tbr', 0),
                'filesize': filesize
            })
        elif vcodec != 'none' and acodec != 'none' and width and height:
            is_original = (
                language_preference == 10 or
                language in ['original', 'default', 'primary'] or
                'original' in str(fmt).lower()
            )
            combined_formats.append({
                'id': format_id,
                'ext': ext,
                'vcodec': vcodec,
                'acodec': acodec,
                'width': width,
                'height': height,
                'tbr': fmt.get('tbr', 0),
                'language': language,
                'language_preference': language_preference,
                'is_original': is_original,
                'filesize': filesize
            })
    # Visibility: counts
    logger.info(f"[{task_id}] JSON formats parsed: video_only={len(video_only_formats)}, audio_only={len(audio_only_formats)}, combined={len(combined_formats)} | target={target_height}p")

    # Strategy 1 (relaxed): Prefer combined MP4 near target, original if available but not required
    if combined_formats:
        combined_formats.sort(key=lambda x: (
            x.get('is_original', False),
            x['ext'] == 'mp4',
            x['height']
        ), reverse=True)

        # Choose best within tolerance or highest
        chosen = None
        for cf in combined_formats:
            if cf['height'] <= int(target_quality.replace('p','')) * 1.2:
                chosen = cf
                break
        if not chosen:
            chosen = combined_formats[0]

        can_copy = (chosen['ext'] == 'mp4')
        estimated_size = chosen.get('filesize', 0)
        logger.info(f"[{task_id}] JSON combined chosen: id={chosen['id']} {chosen['width']}x{chosen['height']} ext={chosen['ext']} orig={chosen.get('is_original', False)} can_copy={can_copy} est_size={estimated_size}")
        return (chosen['id'], can_copy, estimated_size, {'height': chosen['height'], 'video_id': chosen['id']})
    # Strategy 2: Merge video-only + original audio-only
    if video_only_formats and audio_only_formats:
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        def audio_sort_key(fmt):
            is_orig = fmt.get('is_original', False)
            lang_pref = fmt.get('language_preference', -999)
            is_m4a = fmt['ext'] in ['m4a', 'mp4']
            abr = fmt.get('abr', 0)
            return (is_orig, lang_pref, is_m4a, abr)
        audio_only_formats.sort(key=audio_sort_key, reverse=True)
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:
                best_video = fmt
                break
        if not best_video:
            best_video = video_only_formats[0]
        best_audio = audio_only_formats[0]
        
        # LOG ALL AVAILABLE METADATA for selected formats
        logger.info(f"[{task_id}] 🔍 SELECTED VIDEO FORMAT METADATA:")
        for key, value in best_video.items():
            logger.info(f"[{task_id}] 🔍   video.{key}: {value}")
        
        logger.info(f"[{task_id}] 🔍 SELECTED AUDIO FORMAT METADATA:")
        for key, value in best_audio.items():
            logger.info(f"[{task_id}] 🔍   audio.{key}: {value}")
        
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        
        # Extract file sizes with detailed analysis
        video_size = best_video.get('filesize', 0) or best_video.get('filesize_approx', 0) or 0
        audio_size = best_audio.get('filesize', 0) or best_audio.get('filesize_approx', 0) or 0
        estimated_size = video_size + audio_size
        
        # Try to estimate size from bitrate if filesize is missing/wrong
        video_tbr = best_video.get('tbr', 0) or best_video.get('vbr', 0) or 0
        audio_abr = best_audio.get('abr', 0) or 0
        duration = video_duration or best_video.get('duration', 0) or best_audio.get('duration', 0) or 0
        
        # If we still don't have duration, estimate from bitrate and typical video lengths
        if duration == 0 and video_tbr > 0:
            # Estimate duration from audio file size and bitrate
            if audio_size > 0 and audio_abr > 0:
                duration = audio_size * 8 / (audio_abr * 1000)  # Convert back to seconds
                logger.debug(f"[{task_id}] 🔍 Estimated duration from audio: {duration:.1f}s")
            else:
                # Default to 10 minutes for typical videos
                duration = 600
                logger.warning(f"[{task_id}] 🔍 No duration available, assuming 10 minutes")
        
        logger.info(f"[{task_id}] 🔍 SIZE CALCULATION:")
        logger.info(f"[{task_id}] 🔍   video_size (from metadata): {video_size} bytes ({video_size/1024/1024:.1f}MB)")
        logger.info(f"[{task_id}] 🔍   audio_size (from metadata): {audio_size} bytes ({audio_size/1024/1024:.1f}MB)")
        logger.info(f"[{task_id}] 🔍   estimated_size (sum): {estimated_size} bytes ({estimated_size/1024/1024:.1f}MB)")
        logger.info(f"[{task_id}] 🔍   video_tbr: {video_tbr} kbps, audio_abr: {audio_abr} kbps, duration: {duration}s")
        
        # Calculate size from bitrate if available and duration exists
        if duration > 0 and (video_tbr > 0 or audio_abr > 0):
            # Convert kbps to bytes: (kbps * 1000 / 8) * duration_seconds
            video_size_from_br = int((video_tbr * 1000 / 8) * duration) if video_tbr > 0 else 0
            audio_size_from_br = int((audio_abr * 1000 / 8) * duration) if audio_abr > 0 else 0
            total_size_from_br = video_size_from_br + audio_size_from_br
            
            logger.info(f"[{task_id}] 🔍 BITRATE-BASED CALCULATION:")
            logger.info(f"[{task_id}] 🔍   video_size (from bitrate): {video_size_from_br} bytes ({video_size_from_br/1024/1024:.1f}MB)")
            logger.info(f"[{task_id}] 🔍   audio_size (from bitrate): {audio_size_from_br} bytes ({audio_size_from_br/1024/1024:.1f}MB)")
            logger.info(f"[{task_id}] 🔍   total_size (from bitrate): {total_size_from_br} bytes ({total_size_from_br/1024/1024:.1f}MB)")
            
            # Use bitrate calculation if metadata size seems wrong or missing
            if estimated_size == 0 or (estimated_size > 0 and estimated_size < 10_000_000):
                logger.debug(f"[{task_id}] 🔍 Metadata size seems wrong ({estimated_size/1024/1024:.1f}MB), using bitrate calculation instead")
                estimated_size = total_size_from_br
            elif abs(estimated_size - total_size_from_br) > estimated_size * 0.5:  # >50% difference
                logger.debug(f"[{task_id}] 🔍 Large discrepancy between metadata ({estimated_size/1024/1024:.1f}MB) and bitrate ({total_size_from_br/1024/1024:.1f}MB)")
                logger.debug(f"[{task_id}] 🔍 Using average of both: {(estimated_size + total_size_from_br)/2/1024/1024:.1f}MB")
                estimated_size = (estimated_size + total_size_from_br) // 2
        
        # Final sanity check and fallback
        if estimated_size == 0:
            logger.warning(f"[{task_id}] 🔍 No size info available, using 150MB default estimate")
            estimated_size = 150_000_000
        elif estimated_size < 5_000_000:  # Less than 5MB
            logger.warning(f"[{task_id}] 🔍 Size {estimated_size/1024/1024:.1f}MB seems too small, using 100MB estimate")
            estimated_size = 100_000_000
        
        logger.info(f"[{task_id}] 🔍 FINAL RESULT (JSON merge): {merge_format}, size: {estimated_size} bytes ({estimated_size/1024/1024:.1f}MB)")
        return (merge_format, can_copy, estimated_size, {'height': best_video['height'], 'video_id': best_video['id'], 'audio_id': best_audio['id']})
    logger.info(f"[{task_id}] JSON analysis found no suitable formats, will try fallback methods")
    # Why rejected: log top 3 combined with reasons
    if combined_formats:
        top = combined_formats[:3]
        for i, cf in enumerate(top, start=1):
            reason = []
            if cf['height'] > target_height * 1.2:
                reason.append('height>target')
            if cf['ext'] != 'mp4':
                reason.append('ext!=mp4')
            logger.info(f"[{task_id}] ⛔ JSON reject combined#{i}: id={cf['id']} {cf['width']}x{cf['height']} {cf['ext']} orig={cf.get('is_original', False)} reasons={','.join(reason) or 'other'}")
    return None

async def _analyze_formats_from_text(output: str, target_quality: str, task_id: str, known_duration: float = 0) -> Optional[tuple]:
    """Analyze formats from text output with original audio preference and return estimated size (not always possible)"""
    
    lines = output.strip().split('\n')
    
    # Look for format table with more flexible patterns
    table_start = -1
    
    patterns = [
        "ID      EXT   RESOLUTION",  # Standard pattern
        "format code",               # Alternative pattern  
        "ID     EXT  RESOLUTION",    # Slightly different spacing
        "format_id",                 # JSON-like output mixed in
        "---",                       # Separator line
    ]
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for pattern in patterns:
            if pattern.lower() in line_lower:
                table_start = i + 1
                #logger.debug(f"[{task_id}] Found format table at line {i} with pattern '{pattern}'")
                break
        if table_start != -1:
            break
    
    if table_start == -1:
        # Try to find any line that looks like a format
        for i, line in enumerate(lines):
            # Look for lines that start with format ID (number or alphanumeric)
            stripped = line.strip()
            if stripped and len(stripped.split()) >= 3:
                parts = stripped.split()
                # Check if first part looks like a format ID
                if parts[0].replace('-', '').replace('_', '').isalnum():
                    table_start = i
                    #logger.debug(f"[{task_id}] Guessed format table start at line {i}")
                    break
    
    if table_start == -1:
        logger.warning(f"[{task_id}] Could not find format table in text output")
        return None  
    
    # Parse what we can from the text output (simplified approach)
    video_only_formats = []
    audio_only_formats = []
    combined_formats = []
    
    target_height = int(target_quality.replace('p', ''))
    
    # Parse format lines with more flexible approach
    for line in lines[table_start:]:
        line = line.strip()
        if not line or line.startswith('---') or line.startswith('['):
            continue
        
        # Parse format line: ID EXT RESOLUTION FPS CH | FILESIZE TBR PROTO | VCODEC VBR ACODEC ABR ASR MORE INFO
        parts = line.split()
        if len(parts) < 3:
            continue
        
        format_id = parts[0]
        ext = parts[1] 
        resolution = parts[2]
        
        # Check if this is original audio (look for language indicators in the line)
        is_original = any(indicator in line.lower() for indicator in [
            'original', 'default', 'primary', 'first', 'main'
        ])
        
        # Categorize formats
        if resolution == 'audio' or 'audio only' in line.lower():
            # Audio-only format
            audio_only_formats.append({
                'id': format_id,
                'ext': ext,
                'line': line,
                'is_original': is_original
            })
            logger.info(f"[{task_id}]   {format_id}: AUDIO-ONLY ({ext}) - Original: {is_original}")
            
        elif 'video only' in line.lower():
            # Video-only format  
            if 'x' in resolution:
                try:
                    width, height = map(int, resolution.split('x'))
                    video_only_formats.append({
                        'id': format_id,
                        'ext': ext,
                        'width': width,
                        'height': height,
                        'line': line
                    })
                    logger.info(f"[{task_id}]   {format_id}: {width}x{height} ({ext}) - VIDEO-ONLY")
                except ValueError:
                    continue
                    
        elif 'x' in resolution and resolution != 'audio':
            # Combined video+audio format
            try:
                width, height = map(int, resolution.split('x'))
                combined_formats.append({
                    'id': format_id,
                    'ext': ext,
                    'width': width,
                    'height': height,
                    'line': line,
                    'is_original': is_original
                })
            except ValueError:
                continue
    
    # Visibility
    logger.info(f"[{task_id}] Text formats parsed: video_only={len(video_only_formats)}, audio_only={len(audio_only_formats)}, combined={len(combined_formats)}")

    # Strategy 1 (relaxed): Prefer combined MP4 near target
    if combined_formats:
        combined_formats.sort(key=lambda x: (
            x.get('is_original', False),
            x['ext'] == 'mp4',
            x['height']
        ), reverse=True)
        chosen = None
        for fmt in combined_formats:
            if fmt['height'] <= target_height * 1.2:
                chosen = fmt
                break
        if not chosen:
            chosen = combined_formats[0]

        # Prefer merge if combined is low but video-only has good height
        max_vo_height = max([v['height'] for v in video_only_formats], default=0)
        if chosen['height'] < 720 and max_vo_height >= target_height:
            logger.info(f"[{task_id}] TEXT policy: combined too low ({chosen['height']}p) while video-only has {max_vo_height}p; will prefer merge")
        else:
            can_copy = chosen['ext'] == 'mp4'
            estimated_size = 1_000_000_000
            logger.info(f"[{task_id}] TEXT combined chosen: id={chosen['id']} {chosen['width']}x{chosen['height']} ext={chosen['ext']} orig={chosen.get('is_original', False)} can_copy={can_copy} est_size={estimated_size}")
            return (chosen['id'], can_copy, estimated_size, {'height': chosen['height']})
    
    # Strategy 2: Merge best video-only + original audio-only for higher quality
    if video_only_formats and audio_only_formats:
        # Sort video formats: prefer MP4, then by height (descending)
        video_only_formats.sort(key=lambda x: (x['height'], x['ext'] == 'mp4'), reverse=True)
        
        # Sort audio formats: original audio first, then prefer m4a/mp4, then others
        audio_only_formats.sort(key=lambda x: (
            not x.get('is_original', False),  # Original audio first
            x.get('language_preference', -999), # Higher preference = more "original"
            x['ext'] in ['m4a', 'mp4'], # Then prefer m4a/mp4
            x.get('abr', 0) # Then by bitrate
        ), reverse=True)
   
        # Find best video at target quality
        best_video = None
        for fmt in video_only_formats:
            if fmt['height'] <= target_height * 1.2:  # Allow some tolerance
                best_video = fmt
                break
        
        if not best_video:
            # Use highest available video quality
            best_video = video_only_formats[0]
        
        # Use best original audio (prefer m4a/mp4 for compatibility)
        best_audio = audio_only_formats[0]
        
        # Check if we can use fast copy (both MP4-compatible)
        can_copy = (best_video['ext'] == 'mp4' and best_audio['ext'] in ['m4a', 'mp4'])
        
        merge_format = f"{best_video['id']}+{best_audio['id']}"
        is_original = best_audio.get('is_original', False)
        # Estimate size — prefer probing exact sizes, fall back to bitrate*duration
        estimated_size = 0
        # Try parse bitrate from lines
        try:
            v_line = best_video.get('line', '')
            a_line = best_audio.get('line', '')
            v_match = re.search(r'(\d+\.?\d*)k', v_line)
            a_match = re.search(r'(\d+\.?\d*)k', a_line)
            # If we have a known duration (from JSON earlier), use it; else we'll probe later
            duration_guess = int(known_duration) if known_duration and known_duration > 0 else 0
            if v_match:
                v_kbps = float(v_match.group(1))
                if duration_guess > 0:
                    estimated_size += int((v_kbps * 1000 / 8) * duration_guess)
            if a_match:
                a_kbps = float(a_match.group(1))
                if duration_guess > 0:
                    estimated_size += int((a_kbps * 1000 / 8) * duration_guess)
        except Exception:
            pass
        # Let caller refine via dedicated probes; keep placeholder if still zero
        if estimated_size == 0:
            estimated_size = 0
        logger.info(f"[{task_id}] TEXT merge chosen: v={best_video['id']}+a={best_audio['id']} can_copy={can_copy} est_size={estimated_size}")
        return (merge_format, can_copy, estimated_size, {'height': best_video['height'], 'video_id': best_video['id'], 'audio_id': best_audio['id']})
    
    # If we can't find good formats, return None to allow main function's Strategy 3
    logger.warning(f"[{task_id}] Text analysis found no suitable formats, will try fallback methods")
    return None

async def verify_video_quality(video_path: str, task_id: str) -> Optional[str]:
    """Verify the actual quality of a downloaded video using ffprobe"""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode != 0:
            logger.error(f"[{task_id}] Failed to get video info: {result.stderr}")
            return None
        
        data = json.loads(result.stdout)
        
        # Find video stream
        video_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                video_stream = stream
                break
        
        if not video_stream:
            logger.error(f"[{task_id}] No video stream found")
            return None
        
        # Get resolution
        width = video_stream.get('width', 0)
        height = video_stream.get('height', 0)
        
        # Determine quality based on height
        if height >= 1080:
            quality = '1080p'
        elif height >= 720:
            quality = '720p'
        elif height >= 480:
            quality = '480p'
        elif height >= 360:
            quality = '360p'
        elif height >= 240:
            quality = '240p'
        else:
            quality = f"{height}p"
        
        logger.info(f"[{task_id}] Video resolution: {width}x{height} -> {quality}")
        return quality
        
    except Exception as e:
        logger.error(f"[{task_id}] Error verifying video quality: {e}")
        return None

def get_downloaded_bytes(task_id, download_dir):
    """
    Simple function to sum all file sizes in the task-specific download directory.
    Since each task has its own directory, we can safely count all files.
    """
    total = 0
    files_found = []
    
    try:
        if not os.path.exists(download_dir):
            return 0
            
        all_files = os.listdir(download_dir)
        
        # Sum all files in the directory - they all belong to this task
        for fname in all_files:
            fpath = os.path.join(download_dir, fname)
            if os.path.isfile(fpath):
                file_size = os.path.getsize(fpath)
                total += file_size
                files_found.append(f"{fname}:{file_size}")
        
        # Log progress periodically for debugging
        call_key = f"_call_count_{task_id}"
        if hasattr(get_downloaded_bytes, call_key):
            count = getattr(get_downloaded_bytes, call_key) + 1
            setattr(get_downloaded_bytes, call_key, count)
        else:
            count = 1
            setattr(get_downloaded_bytes, call_key, count)
            
        # Enhanced debugging - log more frequently when we have files
        should_log = (count == 1 or count % 12 == 0 or len(files_found) > 0)
        
        if should_log:
            logger.debug(f"[{task_id}] 🔍 Downloads scan #{count}: total={total} bytes from {len(files_found)} files in {download_dir}")
            if len(files_found) <= 20:  # Show files if not too many
                logger.debug(f"[{task_id}] 🔍 Files: {files_found}")
            
            # Also check what's in parent directories for debugging
            if count <= 3:  # Only for first few checks to avoid spam
                try:
                    parent_dir = os.path.dirname(download_dir)
                    if os.path.exists(parent_dir):
                        parent_files = []
                        for fname in os.listdir(parent_dir):
                            fpath = os.path.join(parent_dir, fname)
                            if os.path.isfile(fpath):
                                file_size = os.path.getsize(fpath)
                                parent_files.append(f"{fname}:{file_size}")
                        logger.debug(f"[{task_id}] 🔍 Parent dir ({parent_dir}) files: {parent_files[:10]}")  # Show max 10
                except Exception as e:
                    logger.debug(f"[{task_id}] Could not check parent directory: {e}")
            
    except Exception as e:
        logger.error(f"[{task_id}] Error in get_downloaded_bytes: {e}")
        
    return total

async def handle_youtube_download_task_with_retries(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str):
    """Handle YouTube video download task with simple retry strategy and IP rotation - retries on any error until max attempts"""
    
    max_attempts = 3
    sleep_between_retries = 5  # seconds

    for attempt in range(max_attempts):
        logger.debug(f"[{task_id}] 🚀 Download attempt {attempt + 1}/{max_attempts}")
        
        # Set status to downloading for each attempt
        redis = RedisClient.get_client()
        await redis.set(f"download:{task_id}:status", "downloading", ex=3600)
        logger.debug(f"[{task_id}] ✅ Status set to 'downloading' for attempt {attempt + 1}")

        try:
            # Call the main download handler
            use_cookies = (attempt == max_attempts - 1)
            await handle_youtube_download_task(task_id, video_url, tmdb_id, lang, dub, video_title, video_poster, use_cookies=use_cookies)
            logger.debug(f"[{task_id}] ✅ Download successful on attempt {attempt + 1}")
            return  # Success - exit the retry loop

        except Exception as e:
            if 'do not retry' in str(e):
                await redis.set(f"download:{task_id}:status", "error", ex=3600)
                await redis.set(f"download:{task_id}:error", 'YT-DLP needs update, YT download wont work', ex=3600)
                return

            logger.error(f"[{task_id}] Error on attempt {attempt + 1}: {e}")
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(sleep_between_retries)
                continue
            else:
                logger.error(f"[{task_id}] All {max_attempts} attempts failed")
                redis = RedisClient.get_client()
                await redis.set(f"download:{task_id}:status", "error", ex=3600)
                await redis.set(f"download:{task_id}:error", str(e), ex=3600)
                raise

    # This should never be reached, but just in case
    logger.error(f"[{task_id}] All download attempts failed")
    raise Exception("All download attempts failed")

async def handle_youtube_download_task(task_id: str, video_url: str, tmdb_id: int, lang: str, dub: str, video_title: str, video_poster: str, use_cookies: bool = False):
    """
    Handle YouTube video download task - FULLY NON-BLOCKING
    
    """
    redis = RedisClient.get_client()
    
    # Remove from user's active downloads set when done (success or error)
    tg_user_id = None
    output_path = None
    
    try:
        # Get the best format ID and copy capability
        format_result = await get_best_format_id(video_url, "1080p", task_id, use_cookies=use_cookies)
        
        if not format_result:
            raise Exception("No suitable format found for video")
        
        # Unpack robustly and carry chosen_client once
        chosen_client = "web"
        estimated_size = 0
        if isinstance(format_result, tuple):
            if len(format_result) == 4:
                format_selector, can_copy, estimated_size, chosen_client = format_result
            elif len(format_result) == 3:
                format_selector, can_copy, estimated_size = format_result
            elif len(format_result) == 2:
                format_selector, can_copy = format_result
            else:
                raise Exception(f"Unexpected format_result shape: {format_result!r}")
        else:
            raise Exception(f"Unexpected format_result type: {type(format_result)}")

        # After starting the yt-dlp process, add a background task to periodically check progress by file size
        progress_check_interval = 5  # seconds
        progress_stop_flag = {'stop': False}
        last_progress = 0
        progress_update_min_interval = 1.0
        last_redis_update_ts = 0.0
        
            
        async def progress_watcher():
            nonlocal last_progress
            nonlocal last_redis_update_ts
            start_time = asyncio.get_event_loop().time()
            last_size = 0
            default_size_estimate = 700_000_000  # 700MB default estimate
            loop_count = 0
            
            logger.info(f"[{task_id}] 🔍 Progress watcher started with estimated_size={estimated_size}")
            
            try:
                while not progress_stop_flag['stop']:
                    loop_count += 1
                    downloaded = get_downloaded_bytes(task_id, get_task_download_dir(task_id))
                    
                    # Also check the output file directly (might be growing without temp files)
                    output_file_size = 0
                    if os.path.exists(output_path):
                        output_file_size = os.path.getsize(output_path)
                        if output_file_size > downloaded:
                            downloaded = output_file_size
                            if loop_count % 10 == 1:  # Debug every 10 loops
                                logger.info(f"[{task_id}] 🔍 Using output file size: {output_file_size} bytes ({output_file_size/1024/1024:.1f}MB)")
                    
                    # Enhanced debugging - check multiple locations where yt-dlp might create files
                    if loop_count % 10 == 1:  # First loop and every 10th
                        logger.info(f"[{task_id}] 🔍 Progress debug: loop={loop_count}, downloaded={downloaded}, estimated_size={estimated_size}, last_progress={last_progress}")
                        logger.info(f"[{task_id}] 🔍 Output file exists: {os.path.exists(output_path)}, size: {output_file_size}")
                        
                        # Check for any files matching our task_id pattern in various locations
                        task_pattern_files = []
                        locations_to_check = [
                            get_task_download_dir(task_id),  # Our task directory
                            BASE_DOWNLOAD_DIR,               # Base downloads directory
                            "/tmp",                          # System temp (Linux)
                            "/var/tmp",                      # Alternative temp
                            ".",                             # Current working directory
                        ]
                        
                        for location in locations_to_check:
                            if os.path.exists(location):
                                try:
                                    for fname in os.listdir(location):
                                        if task_id in fname or any(pattern in fname.lower() for pattern in ['.part', '.tmp', '.ytdl', f'{task_id[:8]}']):
                                            fpath = os.path.join(location, fname)
                                            if os.path.isfile(fpath):
                                                file_size = os.path.getsize(fpath)
                                                task_pattern_files.append(f"{location}/{fname}:{file_size}")
                                except Exception as e:
                                    logger.error(f"[{task_id}] Could not check {location}: {e}")
                        
                        if task_pattern_files:
                            logger.info(f"[{task_id}] 🔍 Found task-related files: {task_pattern_files}")
                            # Use the largest file we found as progress
                            largest_size = max(int(f.split(':')[-1]) for f in task_pattern_files)
                            if largest_size > downloaded:
                                downloaded = largest_size
                                logger.info(f"[{task_id}] 🔍 Updated downloaded from task files: {downloaded} bytes")
                        else:
                            logger.info(f"[{task_id}] 🔍 No task-related files found in any location")
                    
                    if estimated_size > 0:
                        percent = min(int((downloaded / estimated_size) * 100), 100)
                        now_ts = asyncio.get_event_loop().time()
                        if percent != last_progress and percent > 0 and (now_ts - last_redis_update_ts >= progress_update_min_interval or percent >= 100):
                            await redis.set(f"download:{task_id}:yt_download_progress", percent, ex=3600)
                            last_progress = percent
                            last_redis_update_ts = now_ts
                            logger.info(f"[{task_id}] Progress: {percent}% ({downloaded}/{estimated_size} bytes)")
                        elif loop_count % 10 == 1:  # Debug every 10 loops
                            logger.info(f"[{task_id}] 🔍 Progress not updated: percent={percent}, last_progress={last_progress}, downloaded={downloaded}")
                                                        
                    elif downloaded > 0:
                        elapsed_time = asyncio.get_event_loop().time() - start_time
                        size_growth = downloaded - last_size
                        last_size = downloaded
                        
                        if elapsed_time > 30 and size_growth > 0:
                            estimated_rate = downloaded / elapsed_time
                            estimated_total_time = max(300, min(900, downloaded / estimated_rate * 3))
                            percent = min(int((elapsed_time / estimated_total_time) * 100), 95)
                        else:
                            percent = min(int((downloaded / default_size_estimate) * 100), 95)
                        
                        now_ts = asyncio.get_event_loop().time()
                        if percent != last_progress and percent > 0 and (now_ts - last_redis_update_ts >= progress_update_min_interval):
                            await redis.set(f"download:{task_id}:yt_download_progress", percent, ex=3600)
                            last_progress = percent
                            last_redis_update_ts = now_ts
                            logger.info(f"[{task_id}] Progress (estimated): {percent}% ({downloaded} bytes downloaded)")
                        elif loop_count % 10 == 1:  # Debug every 10 loops
                            logger.info(f"[{task_id}] 🔍 Progress not updated (no estimate): percent={percent}, last_progress={last_progress}, downloaded={downloaded}")
                    
                    else:
                        # No files detected yet - provide time-based progress estimate
                        elapsed_time = asyncio.get_event_loop().time() - start_time
                        
                        # Adaptive time estimate based on what we know
                        if elapsed_time > 15:  # Start after 15 seconds instead of 30
                            # For very fast downloads (small files), be more aggressive
                            if elapsed_time > 60:
                                # After 1 minute with no progress, something might be wrong OR it's a very slow download
                                time_progress = min(int(10 + (elapsed_time - 60) / 420 * 80), 95)  # 10% to 95% over 7 minutes
                            else:
                                # First minute: slower progress to allow for actual progress to kick in
                                time_progress = min(int((elapsed_time - 15) / 45 * 10), 10)  # 0% to 10% over 45 seconds
                            
                            now_ts = asyncio.get_event_loop().time()
                            if time_progress != last_progress and (now_ts - last_redis_update_ts >= progress_update_min_interval):
                                await redis.set(f"download:{task_id}:yt_download_progress", time_progress, ex=3600)
                                last_progress = time_progress
                                last_redis_update_ts = now_ts
                                logger.info(f"[{task_id}] Progress (time-based fallback): {time_progress}% (no stdout progress detected, elapsed: {elapsed_time:.0f}s)")
                        
                        elif loop_count % 10 == 1:  # Debug when no download detected
                            logger.info(f"[{task_id}] 🔍 No download detected: downloaded={downloaded}, estimated_size={estimated_size}, elapsed={elapsed_time:.0f}s")
                    
                    await asyncio.sleep(progress_check_interval)
                    
            except Exception as e:
                logger.error(f"[{task_id}] ❌ Progress watcher error: {e}", exc_info=True)
            finally:
                logger.info(f"[{task_id}] 🔍 Progress watcher stopped after {loop_count} loops")
                
        progress_task = asyncio.create_task(progress_watcher())
        logger.info(f"[{task_id}] 🔍 Progress watcher task created and started")

        # Download the video
        # IMPORTANT: name the file with a _part0 suffix so upload pipeline can infer part numbering
        output_path = os.path.join(get_task_download_dir(task_id), f"{task_id}_part0.mp4")
        
        if can_copy:
            # Fast path: copy streams (no re-encoding)
            postprocessor_args = "ffmpeg:-c:v copy -c:a copy -bsf:a aac_adtstoasc -avoid_negative_ts make_zero -movflags +faststart"
            logger.info(f"[{task_id}] Using FAST COPY mode")
        else:
            # Slow path: re-encode for compatibility
            postprocessor_args = "ffmpeg:-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k -avoid_negative_ts make_zero -movflags +faststart"
            logger.warning(f"[{task_id}] Using RE-ENCODE mode (slower path)")

        # Build yt-dlp command with enhanced anti-detection
        cmd = [
            "yt-dlp",
            "--ignore-config",
            "-f", format_selector,
            "-o", output_path,
            "--no-playlist",
            "--merge-output-format", "mp4",
            "--postprocessor-args", postprocessor_args,
            "--progress",  # Enable progress reporting
            "--newline",   # Output progress as new lines for easier parsing
            "--concurrent-fragments", "4",
            "--retries", "3",
            "--retry-sleep", "2",
            "--sleep-requests", "0.5",
            "--extractor-args", f"youtube:player_client={chosen_client}",
        ]
        if use_cookies:
            cmd += ["--cookies", "cookies.txt"]
        cmd += [
            "--paths", f"temp:{get_task_download_dir(task_id)}",  # Set temp directory to downloads folder
            video_url
        ]
        
        logger.info(f"[{task_id}] Starting download with format: {format_selector}")
        logger.info(f"[{task_id}] Selection summary | task={task_id} client={chosen_client} selector='{format_selector}' mode={'copy' if can_copy else 're-encode'} est_size={estimated_size}")
        if estimated_size > 0:
            logger.info(f"[{task_id}] Estimated size: {estimated_size} bytes ({estimated_size/1024/1024:.1f}MB)")
        else:
            logger.info(f"[{task_id}] No size estimate available, using adaptive progress tracking")
        logger.info(f"[{task_id}] 🔍 Executing command: {' '.join(cmd)}")
        
        # Run yt-dlp with asyncio.subprocess - CAPTURE STDOUT for progress, stderr for errors
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,  # Progress is output to stdout!
            stderr=asyncio.subprocess.PIPE   # Errors go to stderr
        )

        logger.info(f"[{task_id}] 🔍 Subprocess created with PID: {process.pid}")

        stdout_lines = []
        stderr_lines = []

        async def read_stdout():
            """Read stdout for progress information"""
            nonlocal last_progress
            nonlocal last_redis_update_ts
            frag_tracking_enabled = False  # Flag to track if we're using fragment-based progress
            total_frags = 0  # Store total fragments for consistent tracking
            
            try:
                line_count = 0
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        logger.debug(f"[{task_id}] 🔍 stdout stream ended after {line_count} lines")
                        break
                    line_count += 1
                    decoded = line.decode(errors="ignore").strip()
                    stdout_lines.append(decoded)
                    
                    # Log all stdout output for debugging when few lines
                    if line_count <= 100:  # Log first 100 lines for debugging
                        logger.debug(f"[{task_id}] yt-dlp stdout #{line_count}: {decoded}")
                    
                    # Parse yt-dlp progress output from stdout - PRIORITIZE FRAGMENT TRACKING
                    if '[download]' in decoded:
                        try:
                            percent = None
                            
                            # FIRST PRIORITY: Check for fragment progress
                            frag_match = re.search(r'\(frag (\d+)/(\d+)\)', decoded)
                            if frag_match:
                                current_frag = int(frag_match.group(1))
                                total_frags = int(frag_match.group(2))
                                frag_percent = int((current_frag / total_frags) * 100)
                                
                                # Enable fragment tracking if this is the first time we see it
                                if not frag_tracking_enabled:
                                    frag_tracking_enabled = True
                                    logger.debug(f"[{task_id}] 🔍 Fragment tracking ENABLED: {current_frag}/{total_frags} = {frag_percent}%")
                                
                                percent = frag_percent
                                logger.debug(f"[{task_id}] 🔍 Fragment progress: {current_frag}/{total_frags} = {frag_percent}%")
                            
                            # SECOND PRIORITY: Check for fragment-only progress (no percentage) if fragment tracking not enabled
                            elif not frag_tracking_enabled and ('fragment' in decoded.lower() or 'frag' in decoded):
                                frag_match = re.search(r'(?:fragment|frag)\s+(\d+)\s+of\s+(\d+)', decoded, re.IGNORECASE)
                                
                                if frag_match:
                                    current_frag = int(frag_match.group(1))
                                    total_frags = int(frag_match.group(2))
                                    frag_percent = int((current_frag / total_frags) * 100)
                                    
                                    # Enable fragment tracking
                                    frag_tracking_enabled = True
                                    percent = frag_percent
                                    logger.debug(f"[{task_id}] 🔍 Fragment tracking ENABLED (alternative pattern): {current_frag}/{total_frags} = {frag_percent}%")
                            
                            # THIRD PRIORITY: Use other patterns ONLY if fragment tracking is not enabled
                            elif not frag_tracking_enabled:
                                # Pattern 1: Standard percentage progress
                                # [download] 45.2% of 350.00MiB at 2.50MiB/s ETA 01:23
                                if '%' in decoded:
                                    percent_match = re.search(r'(\d+\.?\d*)%', decoded)
                                    if percent_match:
                                        percent = int(float(percent_match.group(1)))
                                        logger.debug(f"[{task_id}] 🔍 Standard percentage progress: {percent}%")
                                
                                # Pattern 2: File size progress without percentage
                                # [download] 350.00MiB at 2.50MiB/s ETA 01:23
                                elif 'MiB' in decoded or 'MB' in decoded or 'GiB' in decoded or 'GB' in decoded:
                                    # Try to estimate progress from downloaded vs estimated size
                                    size_match = re.search(r'(\d+\.?\d*)\s*(MiB|MB|GiB|GB)', decoded)
                                    if size_match and estimated_size > 0:
                                        downloaded_size_str = size_match.group(1)
                                        unit = size_match.group(2)
                                        
                                        # Convert to bytes
                                        downloaded_bytes = float(downloaded_size_str)
                                        if unit in ['MiB', 'MB']:
                                            downloaded_bytes *= 1024 * 1024 if unit == 'MiB' else 1000 * 1000
                                        elif unit in ['GiB', 'GB']:
                                            downloaded_bytes *= 1024 * 1024 * 1024 if unit == 'GiB' else 1000 * 1000 * 1000
                                        
                                        percent = min(int((downloaded_bytes / estimated_size) * 100), 99)
                                        logger.debug(f"[{task_id}] 🔍 Size-based progress: {downloaded_size_str}{unit} = {percent}%")
                                
                                # Pattern 3: Completion indicators
                                elif 'downloaded' in decoded.lower() and 'completed' not in decoded.lower():
                                    # Look for completion messages
                                    if any(word in decoded.lower() for word in ['finished', 'complete', 'done']):
                                        percent = 100
                                        logger.debug(f"[{task_id}] 🔍 Completion detected: {decoded}")
                            
                            # Update progress if we found any
                            if percent is not None and percent != last_progress and percent > 0:
                                now_ts = asyncio.get_event_loop().time()
                                if now_ts - last_redis_update_ts >= progress_update_min_interval or percent >= 100:
                                    await redis.set(f"download:{task_id}:yt_download_progress", percent, ex=3600)
                                    last_progress = percent
                                    last_redis_update_ts = now_ts
                                    logger.debug(f"[{task_id}] ✅ yt-dlp Progress: {percent}% - {decoded}")
                                
                        except Exception as e:
                            logger.debug(f"[{task_id}] Error parsing progress from stdout: {e}")
                    
                    # Pattern 4: Post-processing progress
                    elif '[ffmpeg]' in decoded:
                        logger.debug(f"[{task_id}] yt-dlp ffmpeg: {decoded}")
                        # Post-processing usually means download is 100%, processing is additional
                        if last_progress < 100:
                            await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
                            last_progress = 100
                            logger.debug(f"[{task_id}] ✅ Download complete, post-processing started")
                    
                    # Pattern 5: File already exists/cached
                    elif 'already' in decoded.lower() and ('exist' in decoded.lower() or 'download' in decoded.lower()):
                        logger.debug(f"[{task_id}] File already exists/cached: {decoded}")
                        await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
                        last_progress = 100
                    
            except Exception as e:
                logger.error(f"[{task_id}] Error reading stdout stream: {e}")
            finally:
                logger.debug(f"[{task_id}] 🔍 stdout reader finished after processing {line_count} lines")

        async def read_stderr():
            """Read stderr for error information"""
            try:
                line_count = 0
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        logger.debug(f"[{task_id}] 🔍 stderr stream ended after {line_count} lines")
                        break
                    line_count += 1
                    decoded = line.decode(errors="ignore").strip()
                    stderr_lines.append(decoded)
                    
                    # Log stderr output for debugging when few lines or important messages
                    if line_count <= 50 or 'ERROR' in decoded.upper() or 'WARNING' in decoded.upper():
                        logger.debug(f"[{task_id}] yt-dlp stderr #{line_count}: {decoded}")
                    
                    # Catch important messages from stderr
                    if 'ERROR' in decoded.upper():
                        logger.error(f"[{task_id}] yt-dlp ERROR: {decoded}")
                    elif 'WARNING' in decoded.upper():
                        logger.warning(f"[{task_id}] yt-dlp WARNING: {decoded}")
                    
            except Exception as e:
                logger.error(f"[{task_id}] Error reading stderr stream: {e}")
            finally:
                logger.debug(f"[{task_id}] 🔍 stderr reader finished after processing {line_count} lines")

        # Set a reasonable timeout for the download (30 minutes max)
        download_timeout = 900  # 20 minutes
        
        try:
            # Run both stdout and stderr readers concurrently with timeout
            await asyncio.wait_for(
                asyncio.gather(
                    read_stdout(),  # Progress tracking from stdout
                    read_stderr()   # Error detection from stderr
                ), 
                timeout=download_timeout
            )
            
            # Wait for process to complete
            returncode = await asyncio.wait_for(process.wait(), timeout=15)
            
        except asyncio.TimeoutError:
            logger.error(f"[{task_id}] Download timed out after {download_timeout} seconds, terminating process")
            
            # Kill the process
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.error(f"[{task_id}] Process didn't terminate gracefully, killing it")
                process.kill()
                await process.wait()
            
            raise Exception(f"Download timed out after {download_timeout/60:.1f} minutes")
        
        # Stop progress watcher
        progress_stop_flag['stop'] = True
        await asyncio.sleep(progress_check_interval)  # Let watcher finish last update
        if not progress_task.done():
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

        # Combine stdout and stderr for error analysis
        stdout_text = '\n'.join(stdout_lines)
        stderr_text = '\n'.join(stderr_lines)
        combined_output = f"STDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}"

        logger.info(f"[{task_id}] Process finished with return code: {returncode}")
        
        # Ensure progress reaches 100% on successful completion
        if returncode == 0 and last_progress < 100:
            await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
            logger.debug(f"[{task_id}] ✅ Process completed successfully, setting progress to 100%")
        
        if returncode != 0:
            error_output = stderr_text or stdout_text or 'Unknown error'
            error_msg = f"yt-dlp failed: {error_output}"
            
            # Check for specific YouTube blocking patterns in both stdout and stderr
            if "HTTP Error 403" in combined_output or "Forbidden" in combined_output:
                logger.warning(f"[{task_id}] YouTube 403 Forbidden detected - likely anti-bot protection")
                raise Exception(f"YouTube blocked access (403 Forbidden): {error_output}")
            elif "fragment 1 not found" in combined_output:
                logger.warning(f"[{task_id}] Fragment not found - likely format availability issue")
                raise Exception(f"Video format not available: {error_output}")
            elif "Requested format is not available" in combined_output:
                logger.warning(f"[{task_id}] Requested format not available - trying different approach")
                raise Exception(f"Format not available: {error_output}")
            elif "YouTube is forcing SABR streaming" in combined_output or "missing a url" in combined_output:
                raise Exception("SABR blocked on all clients")
            else:
                raise Exception(error_msg)
        
        # Check if file was created and has content
        if not os.path.exists(output_path):
            raise Exception("Output file not created")
        
        file_size = os.path.getsize(output_path)
        if file_size == 0:
            os.remove(output_path)
            raise Exception("Downloaded file is empty")
        
        logger.debug(f"[{task_id}] Successfully downloaded: {output_path} ({file_size / (1024*1024):.1f}MB)")
        
        # Verify the actual quality of the downloaded video
        actual_quality = await verify_video_quality(output_path, task_id)
        if actual_quality:
            logger.info(f"[{task_id}] Actual downloaded quality: {actual_quality}")

        # Structured per-task summary with actual size and duration
        actual_duration_seconds = None
        try:
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", output_path
            ]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
            if probe_res.returncode == 0:
                fmt = json.loads(probe_res.stdout).get('format', {})
                if 'duration' in fmt:
                    actual_duration_seconds = float(fmt['duration'])
        except Exception:
            pass
        logger.info(
            f"[{task_id}] Selection summary (final) | task={task_id} client={chosen_client} selector='{format_selector}' "
            f"mode={'copy' if can_copy else 're-encode'} est_size={estimated_size} actual_size={file_size} "
            f"duration={actual_duration_seconds if actual_duration_seconds is not None else 'unknown'}s"
        )
        
        # Continue with upload (this part stays in main process like HDRezka)
        await redis.set(f"download:{task_id}:status", "uploading", ex=3600)
        logger.debug(f"[{task_id}] ✅ Status set to 'uploading' at {datetime.now().isoformat()}")

        # Upload using the shared HDRezka upload pipeline with delivery-bot rotation
        try:
            upload_results = await process_parallel_uploads([output_path], task_id)
            consolidated = await consolidate_upload_results(upload_results, task_id)
            if not consolidated:
                raise Exception("Failed to consolidate upload results.")

            tg_bot_token_file_owner = consolidated["bot_token"]
            parts = consolidated["parts"]
            session_name = consolidated["session_name"]

            # Save in DB using existing structure - handle duplicates gracefully
            async for session in get_db():
                # Check if file already exists
                existing_file = await get_file_id(session, tmdb_id, lang, dub)

                if existing_file:
                    # Update existing record with new file info
                    logger.debug(f"[{task_id}] Updating existing YouTube file record (ID: {existing_file.id})")
                    for attr, value in [
                        ("quality", actual_quality or "unknown"),
                        ("tg_bot_token_file_owner", tg_bot_token_file_owner),
                        ("movie_title", video_title),
                        ("movie_poster", video_poster),
                        ("movie_url", video_url),
                        ("session_name", session_name)
                    ]:
                        setattr(existing_file, attr, value)

                    # Delete old parts and add new ones
                    from sqlalchemy import delete
                    delete_parts_stmt = delete(DownloadedFilePart).where(
                        DownloadedFilePart.downloaded_file_id == existing_file.id
                    )
                    await session.execute(delete_parts_stmt)

                    db_id_to_get_parts = existing_file.id
                else:
                    # Create new record
                    db_entry = DownloadedFile(
                        tmdb_id=tmdb_id,
                        lang=lang,
                        dub=dub,
                        quality=actual_quality or "unknown",
                        tg_bot_token_file_owner=tg_bot_token_file_owner,
                        created_at=datetime.now(timezone.utc),
                        movie_title=video_title,
                        movie_poster=video_poster,
                        movie_url=video_url,
                        session_name=session_name
                    )
                    session.add(db_entry)
                    await session.flush()  # Get db_entry.id
                    db_id_to_get_parts = db_entry.id

                # Add parts (works for both new and updated records)
                if not parts:
                    raise Exception("Upload to Telegram failed: consolidated parts list is empty")
                for part in parts:
                    session.add(DownloadedFilePart(
                        downloaded_file_id=db_id_to_get_parts,
                        part_number=part["part"],
                        telegram_file_id=part["file_id"]
                    ))

                await session.commit()
                break  # Only need one iteration

            await redis.set(f"download:{task_id}:status", "done", ex=3600)

            if len(parts) == 1:
                await redis.set(f"download:{task_id}:result", json.dumps({
                    "tg_bot_token_file_owner": tg_bot_token_file_owner,
                    "telegram_file_id": parts[0]["file_id"]
                }), ex=86400)
            else:
                await redis.set(f"download:{task_id}:result", json.dumps({
                    "db_id_to_get_parts": db_id_to_get_parts,
                }), ex=86400)

            logger.info(f"[{task_id}] YouTube download completed successfully")

        except Exception as upload_error:
            logger.error(f"[{task_id}] Upload failed after successful download: {upload_error}")
            raise
        
        # On completion, set progress to 100
        await redis.set(f"download:{task_id}:yt_download_progress", 100, ex=3600)
        
    except Exception as e:
        logger.error(f"[{task_id}] ❌ Download failed: {e}")
        await notify_admin(f"[Download Task {task_id}] YouTube download failed: {e}")
        raise e
    finally:
        # Get the task-specific download directory for cleanup
        task_download_dir = get_task_download_dir(task_id)
        
        # Clean up downloaded file
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.debug(f"[{task_id}] Cleaned up downloaded file: {output_path}")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to clean up file {output_path}: {e}")
        
        # Clean up the entire task directory and all its contents
        if os.path.exists(task_download_dir):
            try:
                shutil.rmtree(task_download_dir)
                logger.debug(f"[{task_id}] ✅ Cleaned up task directory: {task_download_dir}")
            except Exception as e:
                logger.warning(f"[{task_id}] Failed to clean up directory {task_download_dir}: {e}")
        
        # Remove from user's active downloads set
        if tg_user_id is None:
            # Try to get from Redis
            tg_user_id = await redis.get(f"download:{task_id}:user_id")
        if tg_user_id:
            await redis.srem(f"active_downloads:{tg_user_id}", task_id) # type: ignore
