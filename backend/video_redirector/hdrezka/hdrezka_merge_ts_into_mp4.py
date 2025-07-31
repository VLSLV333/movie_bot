import os
import asyncio
import re
import logging
import time
import psutil
from typing import Dict, Optional
import certifi
import aiohttp
import ssl

from backend.video_redirector.config import MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4
from backend.video_redirector.utils.notify_admin import notify_admin

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logger = logging.getLogger(__name__)
status_tracker: Dict[str, Dict] = {}  # Example: {task_id: {"total": 0, "done": 0, "progress": 0.0}}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_MERGES_OF_TS_INTO_MP4)

def get_system_metrics():
    """Get current system resource usage"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(DOWNLOAD_DIR)
        
        # Get disk I/O stats
        disk_io = psutil.disk_io_counters()
        
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_gb": memory.available / (1024**3),
            "disk_free_gb": disk.free / (1024**3),
            "disk_percent": (disk.used / disk.total) * 100,
            "disk_read_bytes": disk_io.read_bytes if disk_io else 0,
            "disk_write_bytes": disk_io.write_bytes if disk_io else 0,
            "disk_read_count": disk_io.read_count if disk_io else 0,
            "disk_write_count": disk_io.write_count if disk_io else 0
        }
    except Exception as e:
        logger.warning(f"Failed to get system metrics: {e}")
        return {}

async def monitor_system_resources(task_id: str, duration: int = 120):
    """Monitor system resources during merge process"""
    start_time = time.time()
    initial_metrics = get_system_metrics()
    peak_cpu = 0
    peak_memory = 0
    total_disk_writes = 0
    monitoring_samples = 0
    
    logger.info(f"🔍 [{task_id}] Starting system resource monitoring for {duration}s")
    logger.info(f"   Initial - CPU: {initial_metrics.get('cpu_percent', 'N/A')}%, "
                f"Memory: {initial_metrics.get('memory_percent', 'N/A')}%, "
                f"Disk free: {initial_metrics.get('disk_free_gb', 'N/A'):.1f}GB")
    
    while time.time() - start_time < duration:
        try:
            metrics = get_system_metrics()
            cpu = metrics.get('cpu_percent', 0)
            memory = metrics.get('memory_percent', 0)
            disk_writes = metrics.get('disk_write_bytes', 0)
            
            peak_cpu = max(peak_cpu, cpu)
            peak_memory = max(peak_memory, memory)
            total_disk_writes = disk_writes
            monitoring_samples += 1
            
            # Log if resources are high
            if cpu > 80 or memory > 80:
                logger.warning(f"⚠️ [{task_id}] High resource usage - CPU: {cpu}%, Memory: {memory}%")
            
            await asyncio.sleep(5)  # Check every 5 seconds
            
        except Exception as e:
            logger.warning(f"Failed to monitor resources: {e}")
            await asyncio.sleep(5)
    
    # Final resource summary
    final_metrics = get_system_metrics()
    disk_writes_delta = final_metrics.get('disk_write_bytes', 0) - initial_metrics.get('disk_write_bytes', 0)
    
    # Calculate disk I/O speed
    write_speed_mbps = 0
    if disk_writes_delta > 0:
        write_speed_mbps = (disk_writes_delta / (1024**2)) / (duration / 60)  # MB per minute
    
    logger.info(f"📊 [{task_id}] Resource monitoring summary:")
    logger.info(f"   Peak CPU: {peak_cpu}%")
    logger.info(f"   Peak Memory: {peak_memory}%")
    logger.info(f"   Disk writes: {disk_writes_delta / (1024**2):.1f}MB")
    logger.info(f"   Disk I/O speed: {write_speed_mbps:.1f}MB/min")
    logger.info(f"   Monitoring samples: {monitoring_samples}")
    logger.info(f"   Final - CPU: {final_metrics.get('cpu_percent', 'N/A')}%, "
                f"Memory: {final_metrics.get('memory_percent', 'N/A')}%")
    
    # Determine if resources were bottlenecks
    bottlenecks = []
    if peak_cpu > 80:
        bottlenecks.append(f"CPU (peak: {peak_cpu}%)")
    if peak_memory > 80:
        bottlenecks.append(f"Memory (peak: {peak_memory}%)")
    if disk_writes_delta > 0 and write_speed_mbps < 100:  # Less than 100 MB/min
        bottlenecks.append(f"Disk I/O (speed: {write_speed_mbps:.1f}MB/min)")
    
    if bottlenecks:
        logger.warning(f"🚨 [{task_id}] Potential resource bottlenecks detected: {', '.join(bottlenecks)}")
    else:
        logger.info(f"✅ [{task_id}] No resource bottlenecks detected")

async def merge_ts_to_mp4(task_id: str, m3u8_url: str, headers: Dict[str, str]) -> Optional[str]:
    start_time = time.time()
    output_file = os.path.join(DOWNLOAD_DIR, f"{task_id}.mp4")
    ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())

    # Log initial system state
    initial_metrics = get_system_metrics()
    logger.info(f"🚀 [{task_id}] Starting merge - System: CPU={initial_metrics.get('cpu_percent', 'N/A')}%, "
                f"Memory={initial_metrics.get('memory_percent', 'N/A')}%, "
                f"Disk={initial_metrics.get('disk_free_gb', 'N/A'):.1f}GB free")

    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with semaphore:  # simple limiter if many tasks run
            m3u8_start = time.time()
            async with asyncio.timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.get(m3u8_url, headers=headers, ssl=ssl_context) as resp:
                        m3u8_text = await resp.text()
            m3u8_time = time.time() - m3u8_start
            logger.info(f"📋 [{task_id}] M3U8 fetch: {m3u8_time:.2f}s")
    except Exception as e:
        logger.error(f"❌ [{task_id}] Failed to fetch m3u8 file: {e}")
        await notify_admin(f"❌ [{task_id}] Failed to fetch m3u8 file: {e}")
        return None

    try:
        # Analyze playlist structure
        lines = m3u8_text.splitlines()
        segment_count = sum(1 for line in lines if line.strip().endswith(".ts"))
        
        # Extract segment URLs and analyze
        segment_urls = []
        for line in lines:
            if line.strip().endswith(".ts"):
                segment_urls.append(line.strip())
        
        # Log playlist analysis
        logger.info(f"📊 [{task_id}] Playlist analysis: {segment_count} segments, "
                   f"playlist_size={len(m3u8_text)} chars")
        
        if segment_count == 0:
            logger.error(f"❌ [{task_id}] No .ts segments found in playlist")
            await notify_admin(f"❌ [{task_id}] No .ts segments found in playlist")
            return None

        status_tracker[task_id] = {"total": segment_count, "done": 0, "progress": 0.0}
        
        # Enhanced FFmpeg command with performance logging
        cmd = [
            "ffmpeg",
            "-loglevel", "info",
            "-headers", ffmpeg_header_str,
            "-protocol_whitelist", "file,http,https,tcp,tls",
            "-i", m3u8_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            "-y",
            output_file
        ]

        logger.info(f"▶️ [{task_id}] Starting ffmpeg merge for {segment_count} segments...")

        ffmpeg_start = time.time()
        
        # Start system resource monitoring in background
        # Estimate monitoring duration based on segment count (roughly 2-3 minutes for typical merges)
        estimated_duration = min(180, max(60, segment_count * 0.1))  # 0.1s per segment, min 60s, max 180s
        monitor_task = asyncio.create_task(monitor_system_resources(task_id, int(estimated_duration)))
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        ts_opening_pattern = re.compile(r"Opening '.*?\.ts'")
        ts_input_pattern = re.compile(r"Input #\d+.*?\.ts")
        
        processed_segments = 0
        segment_times = []
        last_segment_time = ffmpeg_start

        if process.stdout:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode().strip()
                
                # Enhanced logging for performance analysis
                if "ts" in decoded.lower():
                    logger.debug(f"[{task_id}] FFmpeg: {decoded}")
                
                if (ts_opening_pattern.search(decoded) or 
                    ts_input_pattern.search(decoded) or
                    ".ts" in decoded and ("Opening" in decoded or "Input" in decoded)):
                    current_time = time.time()
                    segment_duration = current_time - last_segment_time
                    segment_times.append(segment_duration)
                    last_segment_time = current_time
                    
                    processed_segments += 1
                    tracker = status_tracker.get(task_id)
                    if tracker:
                        tracker["done"] = processed_segments
                        tracker["progress"] = round((processed_segments / tracker["total"]) * 100, 1)
                        
                        # Log progress every 10% or every 10 segments
                        if processed_segments % max(1, segment_count // 10) == 0 or processed_segments % 10 == 0:
                            avg_segment_time = sum(segment_times[-10:]) / min(len(segment_times), 10)
                            eta = (segment_count - processed_segments) * avg_segment_time
                            logger.info(f"📈 [{task_id}] Progress: {tracker['progress']}% ({processed_segments}/{segment_count}) "
                                      f"Avg segment: {avg_segment_time:.2f}s, ETA: {eta/60:.1f}min")

        returncode = await process.wait()
        total_ffmpeg_time = time.time() - ffmpeg_start
        total_time = time.time() - start_time

        # Cancel monitoring task and wait for it to complete
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # Final performance analysis
        if segment_times:
            avg_segment_time = sum(segment_times) / len(segment_times)
            min_segment_time = min(segment_times)
            max_segment_time = max(segment_times)
            logger.info(f"📊 [{task_id}] Performance Summary:")
            logger.info(f"   Total time: {total_time:.2f}s ({total_time/60:.1f}min)")
            logger.info(f"   FFmpeg time: {total_ffmpeg_time:.2f}s")
            logger.info(f"   M3U8 fetch: {m3u8_time:.2f}s")
            logger.info(f"   Segment processing: {len(segment_times)} segments")
            logger.info(f"   Avg segment time: {avg_segment_time:.2f}s")
            logger.info(f"   Min/Max segment time: {min_segment_time:.2f}s / {max_segment_time:.2f}s")
            logger.info(f"   Throughput: {segment_count/total_ffmpeg_time:.2f} segments/sec")

        if returncode == 0:
            # Get final file size
            file_size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
            logger.info(f"✅ [{task_id}] Merge complete: {output_file} ({file_size_mb:.1f}MB)")
            status_tracker.pop(task_id, None)
            return output_file
        else:
            logger.error(f"❌ [{task_id}] FFmpeg merge failed with code {returncode}")
            await notify_admin(f"❌ [{task_id}] FFmpeg merge failed with return code {returncode}")
            
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                    logger.info(f"🧹 [{task_id}] Removed partial output file after failure.")
                except Exception as e:
                    logger.warning(f"⚠️ [{task_id}] Failed to remove partial file: {e}")

            try:
                del status_tracker[task_id]
            except KeyError:
                pass

            return None

    except Exception as e:
        logger.error(f"❌ [{task_id}] Merge operation failed: {e}")
        await notify_admin(f"❌ [{task_id}] Merge operation failed: {e}")
        
        # Clean up partial file on error
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                logger.info(f"🧹 [{task_id}] Removed partial output file after error.")
            except Exception as cleanup_e:
                logger.warning(f"⚠️ [{task_id}] Failed to remove partial file: {cleanup_e}")

        try:
            del status_tracker[task_id]
        except KeyError:
            pass
        
        return None
    
def get_task_progress(task_id: str) -> Dict:
    if task_id not in status_tracker:
        return {
            "status": "not_found",
            "message": f"No active download task found with ID: {task_id}",
        }

    return {
        "status": "in_progress",
        "message": "Download task is running.",
        **status_tracker[task_id]
    }