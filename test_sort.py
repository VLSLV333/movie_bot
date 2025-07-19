# Test the sorting logic with exact values from logs
formats = [
    {'id': '140-1', 'ext': 'm4a', 'is_original': False, 'language_preference': -1, 'abr': 129.475},
    {'id': '140-5', 'ext': 'm4a', 'is_original': True, 'language_preference': 10, 'abr': 129.475},
    {'id': '249-5', 'ext': 'webm', 'is_original': True, 'language_preference': 10, 'abr': 54.052},
    {'id': '251-5', 'ext': 'webm', 'is_original': True, 'language_preference': 10, 'abr': 146.557},
]

def audio_sort_key(fmt):
    is_orig = fmt.get('is_original', False)
    lang_pref = fmt.get('language_preference', -999)
    is_m4a = fmt['ext'] in ['m4a', 'mp4']
    abr = fmt.get('abr', 0)
    
    sort_key = (not is_orig, -lang_pref, not is_m4a, -abr)
    print(f"Sort key for {fmt['id']}: {sort_key}")
    return sort_key

print("Before sorting:")
for fmt in formats:
    print(f"{fmt['id']}: orig={fmt['is_original']}, lang_pref={fmt['language_preference']}, m4a={fmt['ext'] in ['m4a', 'mp4']}, abr={fmt['abr']}")

formats.sort(key=audio_sort_key, reverse=True)

print("\nAfter sorting:")
for fmt in formats:
    print(f"{fmt['id']}: orig={fmt['is_original']}, lang_pref={fmt['language_preference']}, m4a={fmt['ext'] in ['m4a', 'mp4']}, abr={fmt['abr']}")

print(f"\nFirst format (should be original): {formats[0]['id']}") 