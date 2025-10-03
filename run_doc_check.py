import pathlib
text=pathlib.Path('docs/env_dict.md').read_text(encoding='utf-8')
for name in ['G6_DISABLE_EXPIRY_MAP','G6_EXPIRY_MAP_STRICT','G6_PROFILE_EXPIRY_MAP']:
    print(name, 'FOUND' if name in text else 'MISSING')
