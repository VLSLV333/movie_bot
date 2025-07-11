#!/usr/bin/env python3
"""
Script to copy .ftl files to LC_MESSAGES directories for aiogram_i18n compatibility.
"""

import shutil
from pathlib import Path

def copy_ftl_files():
    """Copy .ftl files from locale directories to their LC_MESSAGES subdirectories."""
    
    # Define the base locales directory
    locales_dir = Path("bot/locales")
    
    if not locales_dir.exists():
        print(f"❌ Locales directory not found: {locales_dir}")
        return
    
    # Find all locale directories
    for locale_dir in locales_dir.iterdir():
        if not locale_dir.is_dir() or locale_dir.name.startswith('.') or locale_dir.name in ['__pycache__']:
            continue
            
        # Look for .ftl files in the locale directory
        ftl_files = list(locale_dir.glob("*.ftl"))
        if not ftl_files:
            print(f"⚠️  No .ftl files found in {locale_dir}")
            continue
            
        # Ensure LC_MESSAGES directory exists
        lc_messages_dir = locale_dir / "LC_MESSAGES"
        lc_messages_dir.mkdir(exist_ok=True)
        
        # Copy each .ftl file to LC_MESSAGES
        for ftl_file in ftl_files:
            target_file = lc_messages_dir / ftl_file.name
            try:
                shutil.copy2(ftl_file, target_file)
                print(f"✅ Copied {ftl_file} -> {target_file}")
            except Exception as e:
                print(f"❌ Failed to copy {ftl_file}: {e}")

    print("🎉 Finished copying .ftl files!")

if __name__ == "__main__":
    copy_ftl_files() 