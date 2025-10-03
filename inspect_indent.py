import pathlib, re
p=pathlib.Path(r'c:\Users\ASUS\Documents\G6\qq\g6_reorganized\src\metrics\metrics.py')
for i,l in enumerate(p.read_text(encoding='utf-8').splitlines(), start=1):
    if 290 <= i <= 306:
        m=re.match(r'^( *)', l)
        spaces=len(m.group(1)) if m else 0
        print(f'{i:04d}: {spaces} spaces -> {l}')