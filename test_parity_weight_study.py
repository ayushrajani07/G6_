import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path('scripts') / 'parity_weight_study.py'


def test_parity_weight_study_synthetic(tmp_path):
    out_file = tmp_path / 'artifact.json'
    # Run synthetic generation with a small sample size for speed
    cmd = [sys.executable, str(SCRIPT), '--synthetic', '8', '--noise', '0.01', '--missing-prob', '0.05', '--out', str(out_file)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Script failed: {result.stderr}\n{result.stdout}"
    assert out_file.exists(), 'Artifact not created'
    data = json.loads(out_file.read_text())
    # Basic schema checks
    assert 'components' in data, 'Missing components section'
    assert 'weight_plan' in data, 'Missing weight_plan section'
    comp = data['components']
    assert isinstance(comp, dict) and comp, 'Components should be a non-empty dict'
    # Ensure at least one component has core statistical fields
    sample_key, sample_val = next(iter(comp.items()))
    for field in ['count', 'mean', 'std', 'min', 'max']:
        assert field in sample_val, f'Missing field {field} in component {sample_key}'
    wp = data['weight_plan']
    for field in ['raw', 'normalized', 'method']:
        assert field in wp, f'Missing field {field} in weight_plan'
    # Normalized weights should sum ~ 1.0 (allow small float diff)
    norm_sum = sum(wp['normalized'].values())
    assert abs(norm_sum - 1.0) < 1e-6, f'Normalized weights sum mismatch: {norm_sum}'
