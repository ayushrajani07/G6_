from __future__ import annotations
import os
import json
import re
from typing import Any, Dict, Optional

# Panels JSON preference and readers

def _use_panels_json() -> bool:
    """
    Decide whether to prefer data/panels/*.json over status fields.
    Controls:
      - G6_SUMMARY_PANELS_MODE: 'on' | 'off' | 'auto' (default 'auto')
      - G6_SUMMARY_READ_PANELS: legacy boolean; respected when MODE isn't set
    In 'auto' mode, if panels appear to come from a simulator (e.g., provider name 'sim'
    or a 'simulator' flag under system), we return False.
    """
    mode = str(os.getenv("G6_SUMMARY_PANELS_MODE", "auto")).strip().lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    # Legacy switch still honored in auto mode when explicitly provided
    legacy = os.getenv("G6_SUMMARY_READ_PANELS")
    if legacy is not None:
        return str(legacy).strip().lower() in ("1", "true", "yes", "on")
    # Heuristic: detect simulator
    try:
        prov = _read_panel_json("provider")
        if isinstance(prov, dict):
            name = str(prov.get("name", prov.get("provider", ""))).strip().lower()
            if name == "sim":
                return False
        sys_pan = _read_panel_json("system")
        if isinstance(sys_pan, dict):
            sim_flag = sys_pan.get("simulator") or sys_pan.get("is_simulator")
            if isinstance(sim_flag, bool) and sim_flag:
                return False
    except Exception:
        pass
    return True


def _panels_dir() -> str:
    return os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))


def _read_panel_json(name: str) -> Optional[Any]:
    if not _use_panels_json():
        return None
    path = os.path.join(_panels_dir(), f"{name}.json")
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict) and "data" in obj:
            return obj.get("data")
        return obj
    except Exception:
        return None


# Log parsing support for indices metrics

def _tail_read(path: str, max_bytes: int = 65536) -> Optional[str]:
    try:
        sz = os.path.getsize(path)
        with open(path, "rb") as f:
            if sz > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return data.decode("latin-1", errors="ignore")
    except Exception:
        return None


def _parse_indices_metrics_from_text(text: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not text:
        return out
    pat = re.compile(r"(?P<idx>[A-Z]{3,10})\s+TOTAL\s+LEGS:\s+(?P<legs>\d+)\s*\|\s*FAILS:\s+(?P<fails>\d+)\s*\|\s*STATUS:\s*(?P<status>[A-Z_]+)")
    for m in pat.finditer(text):
        idx = m.group("idx").strip().upper()
        try:
            legs = int(m.group("legs"))
        except Exception:
            legs = None  # type: ignore
        try:
            fails = int(m.group("fails"))
        except Exception:
            fails = None  # type: ignore
        st = m.group("status").strip().upper()
        out[idx] = {"legs": legs, "fails": fails, "status": st}
    return out


def _get_indices_metrics_from_log() -> Dict[str, Dict[str, Any]]:
    p = os.getenv("G6_INDICES_PANEL_LOG")
    if p and os.path.exists(p):
        txt = _tail_read(p)
        if txt:
            return _parse_indices_metrics_from_text(txt)
    if os.path.exists("g6_platform.log"):
        txt = _tail_read("g6_platform.log")
        if txt:
            return _parse_indices_metrics_from_text(txt)
    return {}


def _get_indices_metrics() -> Dict[str, Dict[str, Any]]:
    if _use_panels_json():
        pj = _read_panel_json("indices")
        if isinstance(pj, dict):
            out: Dict[str, Dict[str, Any]] = {}
            for k, v in pj.items():
                if isinstance(v, dict):
                    out[str(k)] = {**v}
            if out:
                return out
    return _get_indices_metrics_from_log()
