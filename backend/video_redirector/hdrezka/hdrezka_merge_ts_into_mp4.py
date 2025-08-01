import os
import asyncio
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

NUM_OF_MP4_FILES_TO_CREATE = 3

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

async def monitor_parallel_merge_resources(task_id: str, merge_tasks: list, temp_mp4_files: list):
    """
    Monitor system resources during parallel merge process
    Tracks CPU, Memory, Disk I/O, and estimates download speeds
    """
    start_time = time.time()
    initial_metrics = get_system_metrics()
    peak_cpu = 0
    peak_memory = 0
    initial_disk_writes = initial_metrics.get('disk_write_bytes', 0)
    initial_disk_reads = initial_metrics.get('disk_read_bytes', 0)
    monitoring_samples = 0

    logger.info(f"🔍 [{task_id}] Starting parallel merge resource monitoring")
    logger.info(f"   Initial - CPU: {initial_metrics.get('cpu_percent', 'N/A')}%, "
                f"Memory: {initial_metrics.get('memory_percent', 'N/A')}%, "
                f"Disk free: {initial_metrics.get('disk_free_gb', 'N/A'):.1f}GB")
    
    # Monitor until all tasks complete or timeout (30 minutes)
    timeout = 1800  # 30 minutes
    check_interval = 10  # Check every 10 seconds
    
    while time.time() - start_time < timeout:
        try:
            # Check if all merge tasks are complete
            all_complete = all(task.done() for task in merge_tasks)
            
            # Get current system metrics
            metrics = get_system_metrics()
            cpu = metrics.get('cpu_percent', 0)
            memory = metrics.get('memory_percent', 0)
            current_disk_writes = metrics.get('disk_write_bytes', 0)
            current_disk_reads = metrics.get('disk_read_bytes', 0)
            
            # Update peaks
            peak_cpu = max(peak_cpu, cpu)
            peak_memory = max(peak_memory, memory)
            monitoring_samples += 1
            
            # Calculate disk I/O deltas
            disk_writes_delta = current_disk_writes - initial_disk_writes
            disk_reads_delta = current_disk_reads - initial_disk_reads
            
            # Calculate current file sizes and total written
            current_total_size = 0
            current_file_sizes = {}
            for file_path in temp_mp4_files:
                if os.path.exists(file_path):
                    size = os.path.getsize(file_path)
                    current_file_sizes[file_path] = size
                    current_total_size += size
                else:
                    current_file_sizes[file_path] = 0
            
            # Calculate write speeds
            elapsed_minutes = (time.time() - start_time) / 60
            total_written_mb = current_total_size / (1024 * 1024)
            write_speed_mbps = total_written_mb / elapsed_minutes if elapsed_minutes > 0 else 0
            
            # Calculate disk I/O speed
            disk_write_speed_mbps = (disk_writes_delta / (1024**2)) / elapsed_minutes if elapsed_minutes > 0 else 0
            
            # Log progress every 30 seconds or when resources are high
            should_log = (
                monitoring_samples % 3 == 0 or  # Every 30 seconds (3 * 10s)
                cpu > 70 or memory > 70 or  # High resource usage
                all_complete  # Final log when complete
            )
            
            if should_log:
                logger.info(f"📊 [{task_id}] Merge progress - "
                           f"CPU: {cpu:.1f}%, Memory: {memory:.1f}%, "
                           f"Written: {total_written_mb:.1f}MB, "
                           f"Speed: {write_speed_mbps:.1f}MB/min, "
                           f"Disk I/O: {disk_write_speed_mbps:.1f}MB/min")
                
                # Log individual file progress
                for i, file_path in enumerate(temp_mp4_files):
                    if os.path.exists(file_path):
                        current_size = current_file_sizes[file_path]
                        size_mb = current_size / (1024 * 1024)
                        logger.debug(f"   Part {i}: {size_mb:.1f}MB")
            
            # Log warnings for high resource usage
            if cpu > 80 or memory > 80:
                logger.warning(f"⚠️ [{task_id}] High resource usage - CPU: {cpu:.1f}%, Memory: {memory:.1f}%")
            
            # Stop monitoring if all tasks are complete
            if all_complete:
                break
                
            await asyncio.sleep(check_interval)
            
        except Exception as e:
            logger.warning(f"⚠️ [{task_id}] Failed to monitor resources: {e}")
            await asyncio.sleep(check_interval)
    
    # Final resource summary
    final_metrics = get_system_metrics()
    total_time = time.time() - start_time
    final_disk_writes = final_metrics.get('disk_write_bytes', 0)
    final_disk_reads = final_metrics.get('disk_read_bytes', 0)
    
    # Calculate final statistics
    total_disk_writes = final_disk_writes - initial_disk_writes
    total_disk_reads = final_disk_reads - initial_disk_reads
    
    # Get final file sizes
    final_total_size = 0
    final_file_sizes = {}
    for file_path in temp_mp4_files:
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            final_file_sizes[file_path] = size
            final_total_size += size
    
    total_written_mb = final_total_size / (1024 * 1024)
    avg_write_speed_mbps = total_written_mb / (total_time / 60) if total_time > 0 else 0
    avg_disk_write_speed_mbps = (total_disk_writes / (1024**2)) / (total_time / 60) if total_time > 0 else 0
    
    logger.info(f"📊 [{task_id}] Parallel merge resource monitoring summary:")
    logger.info(f"   Duration: {total_time:.1f}s ({total_time/60:.1f}min)")
    logger.info(f"   Peak CPU: {peak_cpu:.1f}%")
    logger.info(f"   Peak Memory: {peak_memory:.1f}%")
    logger.info(f"   Total written: {total_written_mb:.1f}MB")
    logger.info(f"   Average write speed: {avg_write_speed_mbps:.1f}MB/min")
    logger.info(f"   Disk writes: {total_disk_writes / (1024**2):.1f}MB")
    logger.info(f"   Disk I/O speed: {avg_disk_write_speed_mbps:.1f}MB/min")
    logger.info(f"   Monitoring samples: {monitoring_samples}")
    logger.info(f"   Final - CPU: {final_metrics.get('cpu_percent', 'N/A')}%, "
                f"Memory: {final_metrics.get('memory_percent', 'N/A')}%")
                
    return {
        "duration": total_time,
        "peak_cpu": peak_cpu,
        "peak_memory": peak_memory,
        "total_written_mb": total_written_mb,
        "avg_write_speed_mbps": avg_write_speed_mbps,
    }

async def merge_ts_to_mp4(task_id: str, m3u8_url: str, headers: Dict[str, str]) -> Optional[list]:
    """
    Parallel merge strategy: split into 3 chunks, merge in parallel, return list of MP4 files
    Returns: List of MP4 file paths [temp1.mp4, temp2.mp4, temp3.mp4] or None if failed
    """
    start_time = time.time()

    # Log initial system state
    initial_metrics = get_system_metrics()
    logger.info(f"🚀 [{task_id}] Starting parallel merge - System: CPU={initial_metrics.get('cpu_percent', 'N/A')}%, "
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
        
        # Convert relative URLs to absolute URLs
        from urllib.parse import urljoin, urlparse
        
        # Extract base URL from the original m3u8_url
        parsed_url = urlparse(m3u8_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.rsplit('/', 1)[0]}/"
        
        # Convert relative segment URLs to absolute URLs
        absolute_segment_urls = []
        for segment_url in segment_urls:
            if segment_url.startswith('./'):
                # Remove the './' prefix and construct full URL
                relative_path = segment_url[2:]  # Remove './'
                # For these special URLs with :hls:, we need to construct the full URL manually
                absolute_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.rsplit('/', 1)[0]}/{relative_path}"
                absolute_segment_urls.append(absolute_url)
            elif segment_url.startswith('http'):
                # Already absolute
                absolute_segment_urls.append(segment_url)
            else:
                # Relative URL without './' prefix
                absolute_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.rsplit('/', 1)[0]}/{segment_url}"
                absolute_segment_urls.append(absolute_url)
        

        if segment_count == 0:
            logger.error(f"❌ [{task_id}] No .ts segments found in playlist")
            await notify_admin(f"❌ [{task_id}] No .ts segments found in playlist")
            return None

        chunk_size = segment_count // NUM_OF_MP4_FILES_TO_CREATE
        
        # Initialize status tracker for tracking one representative chunk (part 0)
        status_tracker[task_id] = {
            "total": chunk_size,  # Total segments in the representative chunk
            "done": 0,            # Completed segments
            "progress": 0.0       # Progress percentage
        }
        
        logger.info(f"🔄 [{task_id}] Parallel merge: {segment_count} segments → {NUM_OF_MP4_FILES_TO_CREATE} parts "
                   f"(~{chunk_size} segments per part)")
        
        # Create temporary M3U8 files for each chunk
        temp_m3u8_files = []
        temp_mp4_files = []
        
        for part_num in range(NUM_OF_MP4_FILES_TO_CREATE):
            start_idx = part_num * chunk_size
            end_idx = start_idx + chunk_size if part_num < NUM_OF_MP4_FILES_TO_CREATE - 1 else segment_count
            
            # Create temporary M3U8 for this chunk
            temp_m3u8 = os.path.join(DOWNLOAD_DIR, f"{task_id}_part{part_num}.m3u8")
            temp_mp4 = os.path.join(DOWNLOAD_DIR, f"{task_id}_part{part_num}.mp4")
            
            # Write chunk M3U8 (fast string operations)
            chunk_segments = end_idx - start_idx
            with open(temp_m3u8, 'w') as f:
                f.write("#EXTM3U\n")
                f.write("#EXT-X-VERSION:3\n")
                f.write("#EXT-X-TARGETDURATION:10\n")
                f.write("#EXT-X-MEDIA-SEQUENCE:0\n")
                for i in range(start_idx, end_idx):
                    f.write(f"#EXTINF:10.0,\n")
                    f.write(f"{absolute_segment_urls[i]}\n")
                f.write("#EXT-X-ENDLIST\n")
            
            # Log chunk creation details
            logger.debug(f"📝 [{task_id}] Created chunk {part_num}: {temp_m3u8}")
            logger.debug(f"   Segments {start_idx}-{end_idx-1} ({chunk_segments} segments)")
            logger.debug(f"   Output: {temp_mp4}")
            
            # Debug: Log first few lines of the chunked M3U8 file
            if part_num == 0:  # Only log for first chunk to avoid spam
                with open(temp_m3u8, 'r') as f:
                    chunk_lines = f.readlines()
                logger.debug(f"📋 [{task_id}] Sample chunk M3U8 content (first 10 lines):")
                for i, line in enumerate(chunk_lines[:10], 1):
                    logger.debug(f"   {i:2d}: {line.strip()}")
            
            temp_m3u8_files.append(temp_m3u8)
            temp_mp4_files.append(temp_mp4)
        
        # Start parallel merge tasks
        logger.info(f"🚀 [{task_id}] Starting parallel merge of {NUM_OF_MP4_FILES_TO_CREATE} parts...")
        
        merge_tasks = []
        for part_num, temp_m3u8 in enumerate(temp_m3u8_files):
            task = merge_chunk_to_mp4(
                f"{task_id}_part{part_num}", 
                temp_m3u8, 
                temp_mp4_files[part_num], 
                headers
            )
            merge_tasks.append(task)
        
        # Start resource monitoring in parallel with merge tasks
        monitoring_task = asyncio.create_task(
            monitor_parallel_merge_resources(task_id, merge_tasks, temp_mp4_files)
        )
        
        # Wait for all chunks to complete
        chunk_results = await asyncio.gather(*merge_tasks, return_exceptions=True)
        
        # Wait for monitoring to complete and get results
        monitoring_results = await monitoring_task
        
        # Check for failures and update progress
        failed_parts = []
        completed_parts = 0
        for i, result in enumerate(chunk_results):
            if isinstance(result, Exception):
                failed_parts.append(i)
            else:
                completed_parts += 1
        
        if failed_parts:
            logger.error(f"❌ [{task_id}] Failed parts: {failed_parts}")
            await notify_admin(f"❌ [{task_id}] Parallel merge failed on parts: {failed_parts}")
            return None
        
        # Cleanup temporary M3U8 files (keep MP4 files)
        for temp_m3u8 in temp_m3u8_files:
            try:
                os.remove(temp_m3u8)
                logger.debug(f"🧹 [{task_id}] Cleaned up {temp_m3u8}")
            except Exception as e:
                logger.warning(f"⚠️ [{task_id}] Failed to cleanup {temp_m3u8}: {e}")
        
        total_time = time.time() - start_time
        
        # Log final results
        successful_files = [f for f in temp_mp4_files if os.path.exists(f)]
        total_size_mb = sum(os.path.getsize(f) / (1024 * 1024) for f in successful_files)
        
        logger.info(f"✅ [{task_id}] Parallel merge complete: {len(successful_files)} files, "
                   f"total size: {total_size_mb:.1f}MB, time: {total_time:.2f}s ({total_time/60:.1f}min)")
        
        # Log monitoring summary if available
        if monitoring_results:
            logger.info(f"📊 [{task_id}] Performance summary:")
            logger.info(f"   Peak CPU: {monitoring_results.get('peak_cpu', 'N/A'):.1f}%")
            logger.info(f"   Peak Memory: {monitoring_results.get('peak_memory', 'N/A'):.1f}%")
            logger.info(f"   Avg write speed: {monitoring_results.get('avg_write_speed_mbps', 'N/A'):.1f}MB/min")
        
        # Clean up status tracker
        status_tracker.pop(task_id, None)
        
        return successful_files if successful_files else None

    except Exception as e:
        logger.error(f"❌ [{task_id}] Parallel merge operation failed: {e}")
        await notify_admin(f"❌ [{task_id}] Parallel merge operation failed: {e}")
        
        # Clean up status tracker
        status_tracker.pop(task_id, None)
        
        # Clean up any partial files on error
        for temp_file in temp_m3u8_files + temp_mp4_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.debug(f"🧹 [{task_id}] Cleaned up partial file: {temp_file}")
            except Exception as cleanup_e:
                logger.warning(f"⚠️ [{task_id}] Failed to cleanup partial file {temp_file}: {cleanup_e}")
        
        return None

async def merge_chunk_to_mp4(task_id: str, m3u8_file: str, output_file: str, headers: Dict[str, str]) -> bool:
    """Merge a single chunk M3U8 to MP4"""
    chunk_start_time = time.time()
    try:
        # Count segments in this chunk for progress tracking
        with open(m3u8_file, 'r') as f:
            chunk_content = f.read()
        chunk_segments = sum(1 for line in chunk_content.splitlines() if line.strip().endswith(".ts"))
        
        logger.info(f"▶️ [{task_id}] Starting chunk merge: {chunk_segments} segments → {output_file}")

        cmd = [
            "ffmpeg",
            "-loglevel", "warning",  # Less verbose for parallel processing
            "-protocol_whitelist", "file,http,https,tcp,tls",
        ]

        # Optimized FFmpeg command for chunk processing
        cmd.extend([
            "-i", m3u8_file,
            "-c:v", "copy",
            "-c:a", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            "-threads", "2",  # Reduced threads for parallel processing
            "-reconnect", "3",
            "-reconnect_streamed", "3",
            "-reconnect_delay_max", "3",
            "-reconnect_at_eof", "1",
            "-fflags", "+genpts+igndts",
            "-avoid_negative_ts", "make_zero",
            "-max_muxing_queue_size", "1024",
            "-probesize", "1M",
            "-analyzeduration", "10M",
            "-y",
            output_file
        ])
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        # Monitor chunk progress and capture output
        processed_segments = 0
        segment_times = []
        last_segment_time = chunk_start_time
        ffmpeg_output = []
        
        # Check if this is the representative chunk (part 0) for status tracking
        is_representative_chunk = task_id.endswith("_part0")
        
        if process.stdout:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode().strip()
                ffmpeg_output.append(decoded)
                
                # Track segment processing
                if ".ts" in decoded and ("Opening" in decoded or "Input" in decoded):
                    current_time = time.time()
                    segment_duration = current_time - last_segment_time
                    segment_times.append(segment_duration)
                    last_segment_time = current_time
                    
                    processed_segments += 1
                    
                    # Update status tracker for representative chunk only
                    if is_representative_chunk:
                        tracker = status_tracker.get(task_id.replace("_part0", ""))
                        if tracker:
                            tracker["done"] = processed_segments
                            tracker["progress"] = round((processed_segments / tracker["total"]) * 100, 1)
                            
                            # Log progress every 10% or every 10 segments
                            if processed_segments % max(1, chunk_segments // 10) == 0 or processed_segments % 10 == 0:
                                avg_segment_time = sum(segment_times[-10:]) / min(len(segment_times), 10)
                                eta = (chunk_segments - processed_segments) * avg_segment_time
                                logger.info(f"📈 [{task_id}] Progress: {tracker['progress']}% ({processed_segments}/{chunk_segments}) "
                                          f"Avg segment: {avg_segment_time:.2f}s, ETA: {eta/60:.1f}min")
                    
                    # Debug logging for all chunks
                    if processed_segments % 50 == 0:  # Log every 50 segments
                        logger.debug(f"📈 [{task_id}] Progress: {processed_segments}/{chunk_segments} segments")
        
        returncode = await process.wait()
        chunk_time = time.time() - chunk_start_time
        
        if returncode == 0:
            file_size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
            logger.info(f"✅ [{task_id}] Chunk complete: {output_file} ({file_size_mb:.1f}MB, {chunk_time:.2f}s)")
            return True
        else:
            logger.error(f"❌ [{task_id}] Chunk merge failed with code {returncode}")
            logger.error(f"❌ [{task_id}] FFmpeg command: {' '.join(cmd)}")
            logger.error(f"❌ [{task_id}] FFmpeg output (last 20 lines):")
            for line in ffmpeg_output[-20:]:
                logger.error(f"   {line}")
            return False
            
    except Exception as e:
        logger.error(f"❌ [{task_id}] Chunk merge failed: {e}")
        return False
    
def get_task_progress(task_id: str) -> Dict:
    if task_id not in status_tracker:
        return {
            "status": "not_found",
            "message": f"No active download task found with ID: {task_id}",
        }

    tracker = status_tracker[task_id]
    
    return {
        "status": "in_progress",
        "message": f"Parallel merge in progress: {tracker['done']}/{tracker['total']} segments completed in representative chunk.",
        "total": tracker.get("total", 0),
        "done": tracker.get("done", 0),
        "progress": tracker.get("progress", 0.0)
    }