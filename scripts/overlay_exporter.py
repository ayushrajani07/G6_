#!/usr/bin/env python3
"""overlay_exporter.py
Export tp-family signals for Grafana via Prometheus scrape.

What it exposes (all labeled by index, expiry_tag, offset):
- g6_tp, g6_avg_tp: live gauges from the latest row of today's CSV
- g6_tp_mean, g6_tp_ema, g6_avg_tp_mean, g6_avg_tp_ema: weekday overlay values
  for "now" (rounded to 30s) from weekday master CSVs

Notes
- This exporter emits the overlay value corresponding to the current time only.
  As time progresses during the trading day, the time series will trace the
  weekday overlay curve. It does not backfill historical timestamps.
- Defaults are chosen to work with the existing repo layout and mocks.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from prometheus_client import Gauge, start_http_server  # type: ignore
except Exception as e:  # noqa: BLE001
    print(f"prometheus_client not available: {e}")
    raise SystemExit(2) from e


INDEX_DEFAULT = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

# Common synonym mapping between human-friendly and numeric offset names
# Used for directory/file resolution only; labels prefer the CSV row's offset when present
OFFSET_ALIASES: dict[str, str] = {
    "ATM": "0",
    "ITM1": "-1",
    "ITM2": "-2",
    "OTM1": "1",
    "OTM2": "2",
}


def _today_str(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d:%Y-%m-%d}"


def _round_down_30s(dt: datetime) -> str:
    # Return HH:MM:SS string rounded down to nearest 30 seconds
    s = (dt.second // 30) * 30
    return f"{dt:%H:%M}:{s:02d}"


def _parse_float_safe(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


class LastRowCache:
    """Cache last-row lookups by file mtime to avoid repeated full scans."""

    def __init__(self) -> None:
        # path -> (mtime, last_row)
        self._cache: dict[Path, tuple[float, dict[str, str] | None]] = {}

    def get_last_row(self, file_path: Path) -> dict[str, str] | None:
        if not file_path.exists():
            return None
        try:
            mtime = file_path.stat().st_mtime
            cached = self._cache.get(file_path)
            if cached and cached[0] == mtime:
                return cached[1]
            last: dict[str, str] | None = None
            with open(file_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    last = row
            self._cache[file_path] = (mtime, last)
            return last
        except Exception:
            return None


def _compute_live_tp(row: dict[str, str]) -> tuple[float, float]:
    """Return (tp, avg_tp) for a live row.

    Preference order:
    1) Use explicit 'tp' and 'avg_tp' columns if present and numeric
    2) Fallback to computed sums of ce+pe and avg_ce+avg_pe
    """
    # Prefer direct columns
    tp_col = row.get("tp")
    avg_tp_col = row.get("avg_tp")
    tp_v = _parse_float_safe(tp_col, float("nan")) if tp_col is not None else float("nan")
    avg_tp_v = _parse_float_safe(avg_tp_col, float("nan")) if avg_tp_col is not None else float("nan")
    if tp_v == tp_v and avg_tp_v == avg_tp_v:  # not NaN
        return tp_v, avg_tp_v
    # Fallback to sums
    ce = _parse_float_safe(row.get("ce", 0))
    pe = _parse_float_safe(row.get("pe", 0))
    avg_ce = _parse_float_safe(row.get("avg_ce", 0))
    avg_pe = _parse_float_safe(row.get("avg_pe", 0))
    return ce + pe, avg_ce + avg_pe


@dataclass
class OverlayCache:
    mtime: float
    # timestamp string -> (tp_mean, tp_ema, avg_tp_mean, avg_tp_ema)
    by_ts: dict[str, tuple[float, float, float, float]]


class OverlayLookup:
    """Load and cache weekday master overlays for quick lookups."""

    def __init__(self, weekday_root: Path) -> None:
        self.root = weekday_root
        self._cache: dict[Path, OverlayCache] = {}
        # Weekday names used in overlay generator
        self._weekday_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

    def _weekday_dir(self, d: date) -> Path:
        return self.root / self._weekday_names[d.weekday()]

    def _file_for(self, idx: str, expiry_tag: str, offset: str, d: date) -> Path:
        return self._weekday_dir(d) / f"{idx}_{expiry_tag}_{offset}.csv"

    def _load_file(self, path: Path) -> OverlayCache:
        by_ts: dict[str, tuple[float, float, float, float]] = {}
        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    ts = str(r.get("timestamp") or "")
                    if not ts:
                        continue
                    tp_mean = _parse_float_safe(r.get("tp_mean"))
                    tp_ema = _parse_float_safe(r.get("tp_ema"))
                    avg_tp_mean = _parse_float_safe(r.get("avg_tp_mean"))
                    avg_tp_ema = _parse_float_safe(r.get("avg_tp_ema"))
                    by_ts[ts] = (tp_mean, tp_ema, avg_tp_mean, avg_tp_ema)
        except Exception:
            by_ts = {}
        return OverlayCache(mtime=path.stat().st_mtime if path.exists() else 0.0, by_ts=by_ts)

    def get_values(
        self, idx: str, expiry_tag: str, offset: str, now: datetime
    ) -> tuple[float, float, float, float] | None:
        path = self._file_for(idx, expiry_tag, offset, now.date())
        if not path.exists():
            # Try alias for offset (e.g., ATM -> 0)
            alt_off = OFFSET_ALIASES.get(offset)
            if alt_off:
                altp = self._file_for(idx, expiry_tag, alt_off, now.date())
                if altp.exists():
                    path = altp
        if not path.exists():
            # Fallback: search other weekday folders for the same file name (useful on missing weekday master)
            fname = path.name
            for wd in self._weekday_names:
                alt = self.root / wd / fname
                if alt.exists():
                    path = alt
                    break
            else:
                return None
        cached = self._cache.get(path)
        mtime = path.stat().st_mtime
        if cached is None or cached.mtime != mtime:
            cached = self._load_file(path)
            self._cache[path] = cached
        key = _round_down_30s(now)
        return cached.by_ts.get(key)


def run_exporter(
    base_dir: Path,
    weekday_root: Path,
    indices: list[str],
    expiry_tags: list[str],
    offsets: list[str],
    host: str,
    port: int,
    refresh: float,
    status_file: Path | None = None,
) -> None:
    # Gauges for live values (names intentionally match explorer generator expectations)
    g_tp = Gauge("tp", "Total premium (CE+PE) live", ["index", "expiry_tag", "offset"])  # type: ignore
    g_avg = Gauge("avg_tp", "Average premium (avg_ce+avg_pe) live", ["index", "expiry_tag", "offset"])  # type: ignore

    # Gauges for overlay values-at-now
    g_tp_mean = Gauge("tp_mean", "Weekday overlay mean(tp) at current time", ["index", "expiry_tag", "offset"])  # type: ignore
    g_tp_ema = Gauge("tp_ema", "Weekday overlay EMA(tp) at current time", ["index", "expiry_tag", "offset"])  # type: ignore
    g_avg_mean = Gauge("avg_tp_mean", "Weekday overlay mean(avg_tp) at current time", ["index", "expiry_tag", "offset"])  # type: ignore
    g_avg_ema = Gauge("avg_tp_ema", "Weekday overlay EMA(avg_tp) at current time", ["index", "expiry_tag", "offset"])  # type: ignore

    # Analytics (overview + status): PCR per expiry, day_width, and max_pain_strike
    g_pcr = Gauge("pcr", "Put/Call Ratio (per expiry) from overview snapshot", ["index", "expiry_tag"])  # type: ignore
    g_day_width = Gauge("day_width", "Representative day width from overview snapshot", ["index"])  # type: ignore
    g_max_pain = Gauge("max_pain_strike", "Max pain strike (approx) per index", ["index"])  # type: ignore

    start_http_server(port, addr=host)
    print(f"[overlay_exporter] Listening on http://{host}:{port}/metrics")
    print(
        f"[overlay_exporter] base_dir={base_dir} weekday_root={weekday_root} "
        f"indices={indices} expiry_tags={expiry_tags} offsets={offsets}"
    )

    lookup = OverlayLookup(weekday_root)

    # Prefer shared utility cache if available; keep local fallback as future-proof
    try:
        from src.utils.csv_cache import get_last_row_csv, read_json_cached  # type: ignore
    except Exception:
        get_last_row_csv = None  # type: ignore
        read_json_cached = None  # type: ignore
    last_row_cache = LastRowCache()

    def _read_overview_last(index: str, d: date) -> dict[str, str] | None:
        path = base_dir / "overview" / index / f"{d:%Y-%m-%d}.csv"
        if get_last_row_csv:
            from typing import cast as _cast
            return _cast(dict[str, str] | None, get_last_row_csv(path))
        return last_row_cache.get_last_row(path)

    status_cache: dict[str, tuple[float, dict[str, float]]] = {}

    def _read_status_max_pain(sf: Path | None) -> dict[str, float]:
        if not sf:
            return {}
        try:
            if not sf.exists():
                return {}
            mtime = sf.stat().st_mtime
            key = str(sf)
            cached = status_cache.get(key)
            if cached and cached[0] == mtime:
                return cached[1]
            data = read_json_cached(sf) if read_json_cached else json.loads(sf.read_text(encoding="utf-8"))
            mp = data.get("analytics", {}).get("max_pain") or {}
            out: dict[str, float] = {}
            if isinstance(mp, dict):
                for k, v in mp.items():
                    try:
                        out[str(k)] = float(v)
                    except Exception:
                        continue
            status_cache[key] = (mtime, out)
            return out
        except Exception:
            return {}

    def _resolve_live_path(idx: str, exp: str, off: str, today: str) -> tuple[Path, str]:
        """Return (path_to_csv, folder_offset_used).

        Tries the configured offset folder first; if not found, tries alias mapping (e.g., ATM -> 0).
        The returned folder_offset is the directory name used, not the CSV row's offset field.
        """
        p = base_dir / idx / exp / off / f"{today}.csv"
        if p.exists():
            return p, off
        alt = OFFSET_ALIASES.get(off)
        if alt:
            p2 = base_dir / idx / exp / alt / f"{today}.csv"
            if p2.exists():
                return p2, alt
        return p, off

    def _loop() -> None:
        while True:
            # Use explicit timezone to avoid naive datetime; overlays are keyed by local (IST) time-of-day
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            today = _today_str(now.date())
            for idx in indices:
                for exp in expiry_tags:
                    for off in offsets:
                        # live
                        live_path, folder_off = _resolve_live_path(idx, exp, off, today)
                        if get_last_row_csv:
                            row = get_last_row_csv(live_path)
                        else:
                            row = last_row_cache.get_last_row(live_path)
                        if row is not None:
                            tp, avg_tp = _compute_live_tp(row)
                            # Prefer the CSV row's offset value for labeling; fallback to folder name
                            label_off = str(row.get("offset") or folder_off)
                            g_tp.labels(index=idx, expiry_tag=exp, offset=label_off).set(tp)
                            g_avg.labels(index=idx, expiry_tag=exp, offset=label_off).set(avg_tp)
                        # overlay-at-now
                        vals = lookup.get_values(idx, exp, off, now)
                        if vals is not None:
                            tp_m, tp_e, avg_m, avg_e = vals
                            # For overlay labels, stick to the requested offset (may be alias-resolved internally)
                            g_tp_mean.labels(index=idx, expiry_tag=exp, offset=off).set(tp_m)
                            g_tp_ema.labels(index=idx, expiry_tag=exp, offset=off).set(tp_e)
                            g_avg_mean.labels(index=idx, expiry_tag=exp, offset=off).set(avg_m)
                            g_avg_ema.labels(index=idx, expiry_tag=exp, offset=off).set(avg_e)
                # Analytics: last overview row
                over = _read_overview_last(idx, now.date())
                if over is not None:
                    for key, tag in (
                        ("pcr_this_week", "this_week"),
                        ("pcr_next_week", "next_week"),
                        ("pcr_this_month", "this_month"),
                        ("pcr_next_month", "next_month"),
                    ):
                        try:
                            if key in over and over[key] != "":
                                g_pcr.labels(index=idx, expiry_tag=tag).set(float(over[key]))
                        except Exception:
                            pass
                    try:
                        if "day_width" in over and over["day_width"] != "":
                            g_day_width.labels(index=idx).set(float(over["day_width"]))
                    except Exception:
                        pass
                # Max pain from status file (if provided)
                mp_map = _read_status_max_pain(status_file)
                if mp_map:
                    if idx in mp_map:
                        try:
                            g_max_pain.labels(index=idx).set(mp_map[idx])
                        except Exception:
                            pass
            time.sleep(refresh)

    t = threading.Thread(target=_loop, name="overlay-exporter", daemon=True)
    t.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Export tp-family signals as Prometheus metrics"
    )
    p.add_argument(
        "--base-dir",
        default="data/g6_data",
        help="Root of live CSVs (CsvSink output)",
    )
    p.add_argument(
        "--weekday-root",
        default="data/weekday_master",
        help="Root of weekday master overlays",
    )
    p.add_argument(
        "--index",
        dest="indices",
        action="append",
        help="Index (repeatable). Defaults to common set if omitted.",
    )
    p.add_argument(
        "--expiry-tag",
        dest="expiry_tags",
        action="append",
        default=["this_week"],
        help="Expiry tag (repeatable)",
    )
    p.add_argument(
        "--status-file",
        default="data/runtime_status.json",
        help=(
            "Optional runtime status JSON for max pain"
        ),
    )
    p.add_argument(
        "--offset",
        dest="offsets",
        action="append",
        default=["0"],
        help=(
            "Offset name (repeatable). Use numeric '0' for at-the-money; "
            "legacy 'ATM' is accepted as an alias."
        ),
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument(
        "--port",
        type=int,
        default=9109,
        help="Port to expose metrics (avoid 9108 if already used)",
    )
    p.add_argument("--refresh", type=float, default=30.0, help="Seconds between file scans")
    # status-file added above
    args = p.parse_args(argv)

    indices = args.indices or INDEX_DEFAULT
    base = Path(args.base_dir)
    weekday = Path(args.weekday_root)
    try:
        run_exporter(
            base,
            weekday,
            indices,
            args.expiry_tags,
            args.offsets,
            args.host,
            args.port,
            args.refresh,
            Path(args.status_file) if args.status_file else None,
        )
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"overlay_exporter failed: {e}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
