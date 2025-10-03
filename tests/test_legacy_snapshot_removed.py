import importlib
import pytest


def test_legacy_snapshot_tombstone():
    """Assert tombstone module blocks legacy assembler usage.

    Strategy: We keep a lightweight tombstone module temporarily. Import must
    succeed (so stale dependencies fail loudly on attribute access), and
    accessing the removed symbol raises ImportError with guidance.
    """
    mod = importlib.import_module('src.summary.unified.snapshot')
    assert hasattr(mod, '__all__')  # sanity
    with pytest.raises(ImportError):
        getattr(mod, 'assemble_unified_snapshot')

    # Also verify model module does not expose the symbol
    from src.summary.unified import model as model_mod  # type: ignore
    assert 'assemble_unified_snapshot' not in set(getattr(model_mod, '__all__', []))
    assert not hasattr(model_mod, 'assemble_unified_snapshot')
