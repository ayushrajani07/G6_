"""Panels artifact validation helpers.

Provides lightweight JSON Schema validation for PanelsWriter outputs.
Intentionally optional: will noop if jsonschema not installed.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:  # optional dependency
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None  # type: ignore

_SCHEMAS: dict[str, Any] | None = None
_PANEL_SCHEMA_CACHE: Any | None = None


def _load_schemas() -> dict[str, Any]:
    global _SCHEMAS
    if _SCHEMAS is not None:
        return _SCHEMAS
    base = Path(__file__).parent / "schema"
    schemas = {}
    for name in ("manifest.schema.json", "panel_item.schema.json"):
        path = base / name
        try:
            with path.open("r", encoding="utf-8") as f:
                schemas[name] = json.load(f)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed loading schema %s: %s", name, e)
    _SCHEMAS = schemas
    return schemas


def validate_manifest(path: str | Path) -> bool:
    """Validate manifest.json.

    Even when jsonschema dependency is absent we still perform a *minimal* structural
    validation so negative tests (mutation removal of required keys) remain effective.
    """
    # Always attempt to load JSON first; if unreadable fail fast.
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.error("Manifest validation failed: unreadable: %s", e)
        return False
    required_keys = {"generator", "schema_version", "files", "cycle"}
    # Minimal fallback path when jsonschema not installed
    if jsonschema is None:
        missing = [k for k in required_keys if k not in data]
        if missing:
            logger.error("Manifest validation failed (fallback missing=%s)", missing)
            return False
        return True
    # Full schema path
    schemas = _load_schemas()
    schema = schemas.get("manifest.schema.json")
    if not schema:
        # Fall back to minimal required key check
        missing = [k for k in required_keys if k not in data]
        if missing:
            logger.error("Manifest validation failed (no schema; missing=%s)", missing)
            return False
        return True
    try:
        jsonschema.validate(instance=data, schema=schema)  # type: ignore[arg-type]
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise ValueError(f"manifest missing required keys: {missing}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Manifest validation failed: %s", e)
        return False


def validate_panel_generic(path: str | Path) -> bool:
    if jsonschema is None:  # pragma: no cover - optional
        return True
    schemas = _load_schemas()
    schema = schemas.get("panel_item.schema.json")
    if not schema:
        return True
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        jsonschema.validate(instance=data, schema=schema)  # type: ignore[arg-type]
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Panel validation failed (%s): %s", path, e)
        return False


def validate_directory(panels_dir: str | Path) -> dict[str, bool]:
    """Validate known panel artifacts present in a directory.

    Returns mapping of filename->success flag. Missing optional files are skipped.
    """
    panels_dir = Path(panels_dir)
    results: dict[str, bool] = {}
    manifest = panels_dir / "manifest.json"
    if manifest.exists():
        results[manifest.name] = validate_manifest(manifest)
        try:
            with manifest.open("r", encoding="utf-8") as f:
                mf = json.load(f)
            for fname in mf.get("files", []):
                panel_path = panels_dir / fname
                if panel_path.exists():
                    results[fname] = validate_panel_generic(panel_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Error expanding manifest referenced files: %s", e)
    else:
        logger.info("No manifest.json present in %s (maybe basic mode)", panels_dir)
    return results


def runtime_validate_panel(payload: dict[str, Any]) -> None:
    """Validate a panel payload prior to write based on env mode.

    Modes (env G6_PANELS_VALIDATE):
      off    -> do nothing
      warn   -> log warning on failure (default)
      strict -> raise ValueError on failure
    Falls back to 'warn' if invalid/unknown mode specified.
    """
    mode = os.environ.get("G6_PANELS_VALIDATE", "warn").lower()
    if mode not in {"off", "warn", "strict"}:
        mode = "warn"
    if mode == "off" or jsonschema is None:
        return
    global _PANEL_SCHEMA_CACHE
    if _PANEL_SCHEMA_CACHE is None:
        schemas = _load_schemas()
        _PANEL_SCHEMA_CACHE = schemas.get("panel_item.schema.json")
    schema = _PANEL_SCHEMA_CACHE
    if not schema:
        return
    try:
        jsonschema.validate(instance=payload, schema=schema)  # type: ignore[arg-type]
        # Additional strict-only enforcement: require updated_at present at top level
        # Some tests mutate panels to remove updated_at expecting strict mode to fail fast.
        if mode == "strict" and "updated_at" not in payload:
            raise ValueError("runtime panel validation failed: missing 'updated_at'")
    except Exception as e:  # noqa: BLE001
        msg = f"runtime panel validation failed: {e}"
        if mode == "strict":
            raise ValueError(msg) from e
        logger.warning(msg)


def verify_manifest_hashes(panels_dir: str | Path) -> dict[str, str]:
    """Verify hashes in manifest.json against current panel files.

    Returns mapping of filename -> problem description for mismatches / missing.
    Ignores entries with null hashes mapping.
    """
    issues: dict[str, str] = {}
    try:
        panels_path = Path(panels_dir)
        manifest_path = panels_path / 'manifest.json'
        if not manifest_path.exists():
            return {"manifest.json": "missing"}
        with manifest_path.open('r', encoding='utf-8') as f:
            manifest = json.load(f)
        hashes = manifest.get('hashes')
        if not isinstance(hashes, dict):
            return issues  # nothing to verify
        for fname, expected in hashes.items():
            if not isinstance(expected, str) or len(expected) != 64:
                issues[fname] = 'invalid_hash_format'
                continue
            panel_path = panels_path / fname
            if not panel_path.exists():
                issues[fname] = 'file_missing'
                continue
            try:
                with panel_path.open('r', encoding='utf-8') as pf:
                    obj = json.load(pf)
                data_obj = obj.get('data')
                canon = json.dumps(data_obj, sort_keys=True, separators=(',',':')).encode('utf-8') if data_obj is not None else b'null'
                import hashlib as _hashlib
                digest = _hashlib.sha256(canon).hexdigest()
                if digest != expected:
                    issues[fname] = 'mismatch'
            except Exception as e:  # noqa: BLE001
                issues[fname] = f'read_error:{e.__class__.__name__}'
    except Exception as e:  # noqa: BLE001
        issues['__manifest__'] = f'error:{e.__class__.__name__}'
    return issues
