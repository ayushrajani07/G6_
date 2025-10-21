from __future__ import annotations

from pathlib import Path
import hashlib

from src.metrics.generated import SPEC_HASH


def test_metrics_spec_hash_matches_generated_constant() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    spec_path = repo_root / 'metrics' / 'spec' / 'base.yml'
    assert spec_path.exists(), f"Spec file missing: {spec_path}"
    raw = spec_path.read_bytes()
    h = hashlib.sha256(raw).hexdigest()[:16]
    assert h == SPEC_HASH, f"SPEC_HASH out of date: expected {h}, found {SPEC_HASH}"
