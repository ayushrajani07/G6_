import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_FILE = ROOT / 'docs' / 'env_dict.md'
ALLOW = {
    'G6_DISABLE_PER_OPTION_METRICS',
    'G6_MEMORY_TIER_OVERRIDE',
    'G6_TRACE_METRICS',
}

def gather() -> list[str]:
    pattern = re.compile(r'G6_[A-Z0-9_]+')
    found: set[str] = set()
    for base in ['src', 'tests', 'scripts']:
        p = ROOT / base
        if not p.exists():
            continue
        for path in p.rglob('*'):
            if path.is_dir():
                continue
            if any(part.startswith('.') for part in path.parts):
                continue
            if '__pycache__' in path.parts:
                continue
            if path.suffix.lower() not in {'.py', '.md', '.sh', '.bat', '.ps1', '.ini', '.txt'}:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            for m in pattern.findall(text):
                found.add(m)
    try:
        doc_text = DOC_FILE.read_text(encoding='utf-8')
    except FileNotFoundError:
        doc_text = ''
    missing = sorted([n for n in found if n not in ALLOW and n not in doc_text])
    return missing

def main():
    missing = gather()
    print(f"Missing count: {len(missing)}")
    for name in missing:
        print(name)

if __name__ == '__main__':
    main()
