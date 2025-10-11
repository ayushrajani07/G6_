import yaml
import re
from pathlib import Path

# Resolve rules file relative to repo root (tests often execute with CWD at project root,
# but if collected with a different working directory, fallback logic ensures stability).
_TEST_DIR = Path(__file__).resolve().parent

def _find_rules_file() -> Path:
    candidates = [Path.cwd() / "prometheus_rules.yml", _TEST_DIR / ".." / "prometheus_rules.yml"]
    # Walk upward from test directory up to 5 levels
    cur = _TEST_DIR
    for _ in range(5):
        candidates.append(cur / "prometheus_rules.yml")
        cur = cur.parent
    for c in candidates:
        c = c.resolve()
        if c.exists():
            return c
    raise FileNotFoundError("prometheus_rules.yml not found in expected locations: " + ", ".join(str(c) for c in candidates))

RULES_PATH = _find_rules_file()

EXPECTED_ALERTS = [
    {
        "name": "G6PipelineFatalSpike",
        "expr": re.compile(r"g6:pipeline_fatal_ratio_15m\s*>\s*0\.05"),
    },
    {
        "name": "G6PipelineFatalSustained",
        "expr": re.compile(r"g6:pipeline_fatal_ratio_15m\s*>\s*0\.10"),
    },
    {
        "name": "G6PipelineParityFatalCombo",
        "expr": re.compile(r"g6_pipeline_parity_rolling_avg\s*<\s*0\.985.*g6:pipeline_fatal_ratio_15m\s*>\s*0\.05"),
    },
]

def test_fatal_ratio_alert_rules_exist():
    with RULES_PATH.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    found = {a["name"]: False for a in EXPECTED_ALERTS}
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            if "alert" in rule:
                for expected in EXPECTED_ALERTS:
                    if rule["alert"] == expected["name"]:
                        expr = rule.get("expr", "")
                        if expected["expr"].search(expr):
                            found[expected["name"]] = True
    missing = [name for name, ok in found.items() if not ok]
    assert not missing, f"Missing or mismatched fatal ratio alert(s): {missing}"

def _load_text():
    return RULES_PATH.read_text(encoding='utf-8')


def test_recording_rule_exists():
    text = _load_text()
    assert 'record: g6:pipeline_fatal_ratio_15m' in text, 'Recording rule g6:pipeline_fatal_ratio_15m missing'
    # Basic shape of expression (fatal / (fatal+recoverable))
    assert 'pipeline_index_fatal_total' in text and 'pipeline_expiry_recoverable_total' in text


def test_alert_spike_rule():
    text = _load_text()
    # Locate spike alert block
    m = re.search(r'- alert: G6PipelineFatalSpike\n\s+expr: ([^\n]+)', text)
    assert m, 'G6PipelineFatalSpike alert not found'
    expr = m.group(1).strip()
    assert 'g6:pipeline_fatal_ratio_15m > 0.05' in expr
    # Ensure retention window (for:) is present nearby
    after = text[m.end(): m.end() + 120]
    assert 'for:' in after and '10m' in after, 'Spike alert should have for: 10m'


def test_alert_sustained_rule():
    text = _load_text()
    m = re.search(r'- alert: G6PipelineFatalSustained\n\s+expr: ([^\n]+)', text)
    assert m, 'G6PipelineFatalSustained alert not found'
    expr = m.group(1).strip()
    assert 'g6:pipeline_fatal_ratio_15m > 0.10' in expr
    after = text[m.end(): m.end() + 120]
    assert 'for:' in after and '5m' in after, 'Sustained alert should have for: 5m'


def test_combo_alert_rule():
    text = _load_text()
    # Combined parity+fatal alert presence and expression threshold alignment
    m = re.search(r'- alert: G6PipelineParityFatalCombo\n\s+expr: ([^\n]+)', text)
    assert m, 'G6PipelineParityFatalCombo alert not found'
    expr = m.group(1).strip()
    assert 'g6_pipeline_parity_rolling_avg < 0.985' in expr
    assert 'g6:pipeline_fatal_ratio_15m > 0.05' in expr
    after = text[m.end(): m.end() + 120]
    assert 'for:' in after and '5m' in after, 'Combo alert should have for: 5m'
