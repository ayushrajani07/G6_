import pathlib
p=pathlib.Path(r'c:\Users\ASUS\Documents\G6\qq\g6_reorganized\src\metrics\metrics.py')
for i,l in enumerate(p.read_text(encoding='utf-8').splitlines(), start=1):
    if 290 <= i <= 310:
        print(f'{i:04d}: {l}')
