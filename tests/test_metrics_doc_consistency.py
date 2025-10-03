from pathlib import Path
import re

METRICS_PATH = Path(__file__).resolve().parent.parent / 'src' / 'metrics' / 'metrics.py'


def test_always_on_metrics_have_doc_comment():
    text = METRICS_PATH.read_text(encoding='utf-8').splitlines()
    content = '\n'.join(text)
    # Extract always_on metrics list via append patterns
    always_on = set(re.findall(r"_always_on_metrics.append\('(.*?)'\)", content))
    # Build map metric -> found METRIC doc block
    metric_docs = {}
    current_ids = []
    for i, line in enumerate(text):
        if '# METRIC:' in line:
            after = line.split('# METRIC:',1)[1].strip()
            ids = after.split()[0]
            current_ids = [m.strip() for m in ids.split('/') if m.strip()]
            # Capture following comment lines as description
            desc_lines = []
            j = i + 1
            while j < len(text):
                nxt = text[j]
                if not nxt.strip():
                    break
                if '# METRIC:' in nxt:
                    break
                if nxt.lstrip().startswith('#'):
                    desc_lines.append(nxt.lstrip().lstrip('#').strip())
                    j += 1
                    continue
                break
            description = ' '.join(desc_lines).strip()
            for mid in current_ids:
                metric_docs[mid] = description
    missing = [m for m in always_on if m not in metric_docs]
    assert not missing, f"Always-on metrics missing # METRIC doc comment: {missing}"
