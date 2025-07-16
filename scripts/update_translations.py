#!/usr/bin/env python3
"""
Translation management script for Movie Bot (aiogram-compatible).

This script provides utilities for:
1. Extracting translatable strings from source code
2. Updating existing translation files
3. Compiling translations to .mo files for aiogram
4. Creating new language files

Usage:
    python scripts/update_translations.py [command]

Commands:
    extract     - Extract translatable strings from source code
    update      - Update existing translation files
    compile     - Compile .po files to .mo files for aiogram
    init        - Initialize new language (requires --lang parameter)
    all         - Run extract, update, and compile (default)
"""

import subprocess
import sys
import argparse
import re
from pathlib import Path
from typing import Set


def find_translation_keys() -> Set[str]:
    """
    Find all translation keys used in the codebase.
    Looks for gettext() calls and keys from bot/locales/keys.py
    """
    keys = set()
    
    # Find all gettext() calls
    for py_file in Path('.').rglob('*.py'):
        if 'venv' in str(py_file) or '__pycache__' in str(py_file):
            continue
            
        try:
            content = py_file.read_text(encoding='utf-8')
            # Find gettext calls with string literals
            matches = re.findall(r'gettext\(["\']([^"\']+)["\']\)', content)
            keys.update(matches)
        except Exception as e:
            print(f"Warning: Could not read {py_file}: {e}")
    
    # Also get keys from keys.py
    keys_file = Path('bot/locales/keys.py')
    if keys_file.exists():
        try:
            content = keys_file.read_text(encoding='utf-8')
            # Find key assignments
            matches = re.findall(r'(\w+)\s*=\s*["\']([^"\']+)["\']', content)
            for var_name, key_value in matches:
                keys.add(key_value)
        except Exception as e:
            print(f"Warning: Could not read keys.py: {e}")
    
    return keys


def extract_strings():
    """Extract translatable strings from source code."""
    print("⏳ Extracting translatable strings...")
    
    keys = find_translation_keys()
    
    # Create messages.pot file
    pot_content = f"""# English translations for Movie Bot
# Language: English (US)
# Charset: UTF-8

msgid ""
msgstr ""
"Project-Id-Version: Movie Bot\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: 2024-01-01 00:00+0000\\n"
"PO-Revision-Date: 2024-01-01 00:00+0000\\n"
"Language: en\\n"
"Language-Team: English\\n"
"Plural-Forms: nplurals=2; plural=(n != 1)\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"

"""
    
    # Add all keys
    for key in sorted(keys):
        pot_content += f'msgid "{key}"\n'
        pot_content += f'msgstr ""\n\n'
    
    # Write to messages.pot
    pot_file = Path('bot/locales/messages.pot')
    pot_file.write_text(pot_content, encoding='utf-8')
    
    print(f"✅ Extracted {len(keys)} translatable strings to bot/locales/messages.pot")
    return True


def update_translations():
    """Update existing translation files."""
    print("⏳ Updating translation files...")
    
    pot_file = Path('bot/locales/messages.pot')
    if not pot_file.exists():
        print("❌ messages.pot file not found. Run 'extract' first.")
        return False
    
    # Get all language directories
    locales_dir = Path('bot/locales')
    language_dirs = [d for d in locales_dir.iterdir() if d.is_dir() and d.name in ['en', 'uk', 'ru']]
    
    for lang_dir in language_dirs:
        lang = lang_dir.name
        po_file = lang_dir / 'LC_MESSAGES' / 'messages.po'
        
        if po_file.exists():
            print(f"  Updating {lang} translations...")
            # Read existing translations
            existing_translations = {}
            try:
                content = po_file.read_text(encoding='utf-8')
                # Parse existing msgid/msgstr pairs
                matches = re.findall(r'msgid "([^"]*)"\nmsgstr "([^"]*)"', content)
                for msgid, msgstr in matches:
                    if msgid:  # Skip empty msgid (header)
                        existing_translations[msgid] = msgstr
            except Exception as e:
                print(f"    Warning: Could not read existing {lang} translations: {e}")
            
            # Read new keys from pot file
            pot_content = pot_file.read_text(encoding='utf-8')
            new_keys = re.findall(r'msgid "([^"]*)"', pot_content)
            
            # Create updated po content
            po_content = f"""# {lang.upper()} translations for Movie Bot
# Language: {lang.upper()}
# Charset: UTF-8

msgid ""
msgstr ""
"Project-Id-Version: Movie Bot\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: 2024-01-01 00:00+0000\\n"
"PO-Revision-Date: 2024-01-01 00:00+0000\\n"
"Language: {lang}\\n"
"Language-Team: {lang.upper()}\\n"
"Plural-Forms: nplurals=2; plural=(n != 1)\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"

"""
            
            # Add all keys with existing translations or empty strings
            for key in sorted(new_keys):
                if key:  # Skip empty key (header)
                    po_content += f'msgid "{key}"\n'
                    po_content += f'msgstr "{existing_translations.get(key, "")}"\n\n'
            
            # Write updated po file
            po_file.write_text(po_content, encoding='utf-8')
            print(f"    ✅ Updated {lang} translations")
    
    print("✅ Translation files updated")
    return True


def compile_translations():
    """Compile .po files to .mo files for aiogram."""
    print("⏳ Compiling translation files...")
    
    try:
        # Use msgfmt from gettext tools
        locales_dir = Path('bot/locales')
        language_dirs = [d for d in locales_dir.iterdir() if d.is_dir() and d.name in ['en', 'uk', 'ru']]
        
        for lang_dir in language_dirs:
            lang = lang_dir.name
            po_file = lang_dir / 'LC_MESSAGES' / 'messages.po'
            mo_file = lang_dir / 'LC_MESSAGES' / 'messages.mo'
            
            if po_file.exists():
                print(f"  Compiling {lang} translations...")
                try:
                    # Use msgfmt to compile .po to .mo
                    result = subprocess.run(
                        ['msgfmt', str(po_file), '-o', str(mo_file)],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    print(f"    ✅ Compiled {lang} translations")
                except subprocess.CalledProcessError as e:
                    print(f"    ❌ Failed to compile {lang}: {e.stderr}")
                    return False
                except FileNotFoundError:
                    print(f"    ❌ msgfmt not found. Please install gettext tools.")
                    print(f"       On Ubuntu/Debian: sudo apt-get install gettext")
                    print(f"       On macOS: brew install gettext")
                    print(f"       On Windows: Download from https://mlocati.github.io/articles/gettext-iconv-windows.html")
                    return False
        
        print("✅ Translation files compiled")
        return True
        
    except Exception as e:
        print(f"❌ Compilation failed: {e}")
        return False


def init_language(lang_code):
    """Initialize a new language."""
    if not lang_code:
        print("❌ Language code is required for init command")
        return False
    
    print(f"⏳ Initializing language: {lang_code}")
    
    # Create language directory structure
    lang_dir = Path(f'bot/locales/{lang_code}/LC_MESSAGES')
    lang_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy template from English
    en_po = Path('bot/locales/en/LC_MESSAGES/messages.po')
    new_po = lang_dir / 'messages.po'
    
    if en_po.exists():
        content = en_po.read_text(encoding='utf-8')
        # Update language headers
        content = content.replace('Language: en', f'Language: {lang_code}')
        content = content.replace('Language-Team: English', f'Language-Team: {lang_code.upper()}')
        # Clear all translations (keep msgid, empty msgstr)
        content = re.sub(r'msgstr "[^"]*"', 'msgstr ""', content)
        
        new_po.write_text(content, encoding='utf-8')
        print(f"✅ Initialized {lang_code} language file")
        return True
    else:
        print("❌ English translation file not found. Run 'extract' first.")
        return False


def check_msgfmt_installed():
    """Check if msgfmt is installed."""
    try:
        subprocess.run(['msgfmt', '--version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ msgfmt is not installed or not in PATH")
        print("   Please install gettext tools:")
        print("   - Ubuntu/Debian: sudo apt-get install gettext")
        print("   - macOS: brew install gettext")
        print("   - Windows: Download from https://mlocati.github.io/articles/gettext-iconv-windows.html")
        return False


def check_project_structure():
    """Check if we're in the correct project directory."""
    current_dir = Path.cwd()
    required_files = [
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
        description="Movie Bot Translation Management (aiogram-compatible)",
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
    
    print("🚀 Movie Bot Translation Management (aiogram-compatible)")
    print("=" * 50)
    
    # Check project structure
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