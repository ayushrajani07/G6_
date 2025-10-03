from __future__ import annotations

import json
import os
import shutil
from typing import Any


def _clean_panels(tmp_dir: str) -> None:
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)


def test_panels_transaction_commit(tmp_path):
    base = tmp_path / "panels"
    os.environ["G6_OUTPUT_SINKS"] = "panels"
    os.environ["G6_PANELS_DIR"] = str(base)
    from src.utils.output import get_output

    router = get_output(reset=True)

    # Begin a transaction and write two panels
    with router.begin_panels_txn() as txn:
        router.panel_update("provider", {"name": "T"})
        router.panel_update("resources", {"cpu": 1})
        # while in transaction, destination files should not exist
        assert not (base / "provider.json").exists()
        assert not (base / "resources.json").exists()
        # staging should exist
        stage_dir = base / ".txn" / txn.id
        assert stage_dir.exists()
        # staged files exist
        assert (stage_dir / "provider.json").exists()
        assert (stage_dir / "resources.json").exists()
    # After context, commit should have been called
    assert (base / "provider.json").exists()
    assert (base / "resources.json").exists()
    # meta written
    meta_path = base / ".meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text("utf-8"))
    assert "last_txn_id" in meta and isinstance(meta.get("panels"), list)


def test_panels_transaction_abort(tmp_path):
    base = tmp_path / "panels2"
    os.environ["G6_OUTPUT_SINKS"] = "panels"
    os.environ["G6_PANELS_DIR"] = str(base)
    from src.utils.output import get_output

    router = get_output(reset=True)

    # Abort path: manually use context and trigger exception
    try:
        with router.begin_panels_txn() as txn:
            router.panel_update("provider", {"name": "X"})
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    # No panel files should exist on abort
    assert not (base / "provider.json").exists()
    # Staging dir should be gone
    assert not (base / ".txn").exists() or not any((base / ".txn").iterdir())
