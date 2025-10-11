import pathlib
p=pathlib.Path('src/collectors/pipeline/parity.py')
for i,l in enumerate(p.read_text().splitlines(),1):
    print(f'{i:04d}: {l}')
