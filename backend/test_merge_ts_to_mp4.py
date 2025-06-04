import os
import subprocess
import requests
import time
import threading
import re
import certifi

DOWNLOAD_DIR = "downloads"
DIRECT_M3U8_URL = "https://prx-cogent.ukrtelcdn.net/s__green/c200b0a6e23f26f0e6de921d0dd8d7e3:2025060406:OUp5QkVCK0tzRkREb2xQanB0TVBHbWdLRHFKOXV1SGV6czdwa2lFL2RkMXdjTlR3Y3NLbFloeS9lczRRb1hPdy9IVFZJSFR3RndUZmpIOGdQWWdHUkE9PQ==/3/5/1/5/8/5/0ml6f.mp4:hls:manifest.m3u8"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",
    "Origin": "https://hdrezka.ag",
    "Referer": "https://hdrezka.ag/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site"
}

ffmpeg_header_str = ''.join(f"{k}: {v}\r\n" for k, v in headers.items())

# Save m3u8 locally (optional, just to count segments)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
r = requests.get(DIRECT_M3U8_URL, headers=headers, timeout=10, verify=certifi.where())
r.raise_for_status()

m3u8_path = os.path.join(DOWNLOAD_DIR, "movie.m3u8")
with open(m3u8_path, "w", encoding="utf-8") as f:
    f.write(r.text)

segment_count = sum(1 for line in r.text.splitlines() if line.strip().endswith(".ts"))
print(f"📦 Found {segment_count} video segments to merge.")

# ffmpeg command
output_file = os.path.join(DOWNLOAD_DIR, "merged_output.mp4")
cmd = [
    "ffmpeg",
    "-loglevel", "info",
    "-headers", ffmpeg_header_str,
    "-protocol_whitelist", "file,http,https,tcp,tls",
    "-i", DIRECT_M3U8_URL,
    "-c", "copy",
    "-bsf:a", "aac_adtstoasc",
    output_file
]

print("\nRunning ffmpeg...\n")
start_time = time.time()

merged_segments = 0
ffmpeg_output = []

# Run ffmpeg
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

# Heartbeat logger
def heartbeat():
    while process.poll() is None:
        percent = (merged_segments / segment_count) * 100
        print(f"⏳ ffmpeg is running... merged ~{merged_segments}/{segment_count} segments ({percent:.1f}%)")
        time.sleep(15)

threading.Thread(target=heartbeat, daemon=True).start()

# Track progress
segment_pattern = re.compile(r"Opening '.*?\.ts'")
for line in process.stdout:
    ffmpeg_output.append(line)
    if segment_pattern.search(line):
        merged_segments += 1

process.wait()


# Final summary
elapsed = time.time() - start_time
minutes, seconds = int(elapsed // 60), int(elapsed % 60)

if process.returncode == 0:
    print("\n✅ ffmpeg completed successfully.")
    print(f"🔗 Output saved to: {output_file}")
    print(f"🕒 Total processing time: {minutes}m {seconds}s")
else:
    print("\n❌ ffmpeg failed!")
    print("📄 Last few output lines:")
    print("\n".join(ffmpeg_output[-20:]))

print(f"\n✅ Merged video saved to: {output_file}")