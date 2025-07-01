import json
from pyrogram import Client

CONFIG_PATH = "app/backend/video_redirector/utils/upload_accounts.json"
SESSION_DIR = "app/backend/session_files"  # Make sure this directory exists

with open(CONFIG_PATH, "r") as f:
    accounts = json.load(f)

for acc in accounts:
    print(f"Setting up session for: {acc['session_name']}")
    session_path = f"{SESSION_DIR}/{acc['session_name']}"
    app = Client(
        session_path,
        api_id=acc["api_id"],
        api_hash=acc["api_hash"]
    )
    with app:
        print(f"Session for {acc['session_name']} created and saved.")