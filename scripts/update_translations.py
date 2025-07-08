#!/usr/bin/env python3
"""
Translation management script for Movie Bot.

This script provides utilities for:
1. Extracting translatable strings from source code
2. Updating existing translation files
3. Compiling translations to .mo files
4. Creating new language files

Usage:
    python scripts/update_translations.py [command]

Commands:
    extract     - Extract translatable strings from source code
    update      - Update existing translation files
    compile     - Compile .po files to .mo files
    init        - Initialize new language (requires --lang parameter)
    all         - Run extract, update, and compile (default)
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"⏳ {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"   Command: {cmd}")
        print(f"   Error: {e.stderr}")
        return False


def extract_strings():
    """Extract translatable strings from source code."""
    cmd = 'pybabel extract -F babel.cfg -k __ -o bot/locales/messages.pot .'
    return run_command(cmd, "Extracting translatable strings")


def update_translations():
    """Update existing translation files."""
    cmd = 'pybabel update -i bot/locales/messages.pot -d bot/locales'
    return run_command(cmd, "Updating translation files")


def compile_translations():
    """Compile .po files to .mo files."""
    cmd = 'pybabel compile -d bot/locales'
    return run_command(cmd, "Compiling translation files")


def init_language(lang_code):
    """Initialize a new language."""
    if not lang_code:
        print("❌ Language code is required for init command")
        return False
    
    cmd = f'pybabel init -i bot/locales/messages.pot -d bot/locales -l {lang_code}'
    return run_command(cmd, f"Initializing language: {lang_code}")


def check_babel_installed():
    """Check if pybabel is installed."""
    try:
        subprocess.run(['pybabel', '--version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ pybabel is not installed or not in PATH")
        print("   Please install with: pip install babel")
        return False


def check_project_structure():
    """Check if we're in the correct project directory."""
    current_dir = Path.cwd()
    required_files = [
        'babel.cfg',
        'bot/locales',
        'bot/main.py'
    ]
    
    missing_files = []
    for file_path in required_files:
        if not (current_dir / file_path).exists():
            missing_files.append(file_path)
    
    if missing_files:
        print("❌ Project structure check failed. Missing files/directories:")
        for file_path in missing_files:
            print(f"   - {file_path}")
        print("\nPlease run this script from the project root directory.")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Movie Bot Translation Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'command',
        nargs='?',
        default='all',
        choices=['extract', 'update', 'compile', 'init', 'all'],
        help='Command to run (default: all)'
    )
    
    parser.add_argument(
        '--lang',
        help='Language code for init command (e.g., es, fr, de)'
    )
    
    args = parser.parse_args()
    
    print("🚀 Movie Bot Translation Management")
    print("=" * 40)
    
    # Check prerequisites
    if not check_babel_installed():
        sys.exit(1)
    
    if not check_project_structure():
        sys.exit(1)
    
    # Execute commands
    success = True
    
    if args.command == 'extract':
        success = extract_strings()
    elif args.command == 'update':
        success = update_translations()
    elif args.command == 'compile':
        success = compile_translations()
    elif args.command == 'init':
        success = init_language(args.lang)
    elif args.command == 'all':
        success = (
            extract_strings() and
            update_translations() and
            compile_translations()
        )
    
    if success:
        print("\n🎉 Translation management completed successfully!")
        print("\nNext steps:")
        print("1. Review and translate any new strings in .po files")
        print("2. Run 'python scripts/update_translations.py compile' after making changes")
        print("3. Test your bot with different language settings")
    else:
        print("\n❌ Translation management failed!")
        sys.exit(1)


if __name__ == "__main__":
    main() 