"""Plugin base interfaces for unified summary + panels loop.

Architecture Overview (Phase 1):
---------------------------------
The unified summary loop constructs a `SummarySnapshot` each cycle. Output
plugins can optionally enrich the *mutable* status dict embedded inside the
snapshot (e.g., injecting `panel_push_meta` diagnostics) while treating the
dataclass container itself as immutable. This enables side-channel data such as
SSE ingestion state, diff counters, heartbeat freshness, and rendered panel
metadata to appear uniformly across renderers without tightly coupling the
core loop to specific transport concerns.

Key Plugin Responsibilities:
* setup(context): Perform one-time initialization (spawn threads, open files).
* process(snapshot): Read snapshot fields and (optionally) mutate nested dict
    structures for diagnostics. Must be fast and avoid blocking long IO paths.
* teardown(): Release resources.

Mutation Safety:
Only the nested `snapshot.status` mapping is considered mutable. Code should
avoid reassigning top-level attributes of the dataclass. This pattern keeps
the contract simple while still allowing rich debug / meta injection.

Future Phases:
Async scheduling, per-plugin interval hints, and stricter typed models may be
introduced; current design keeps surface minimal to accelerate iteration.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from scripts.summary.domain import SummaryDomainSnapshot  # pragma: no cover
    from src.summary.unified.model import UnifiedStatusSnapshot  # pragma: no cover
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SummarySnapshot:
    """Immutable in-memory representation of a cycle's computed state.

    Fields intentionally coarse for now; refined types can replace the dicts
    once unification stabilizes.
    """
    status: Mapping[str, Any]
    derived: Mapping[str, Any]
    panels: Mapping[str, Any]
    ts_read: float
    ts_built: float
    cycle: int
    errors: Sequence[str]
    # Phase 2 dual emission: unified model snapshot (authoritative structured representation)
    model: UnifiedStatusSnapshot | None = None  # populated by loop when available
    # Phase 2: domain snapshot (new structured representation replacing ad-hoc derived/panels maps gradually)
    domain: SummaryDomainSnapshot | None = None
    # Phase 4 optimization: optional shared panel hash map (populated by first hashing plugin)
    panel_hashes: dict[str, str] | None = None

class OutputPlugin(Protocol):
    """Contract each output writer/renderer implements."""
    name: str

    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover - trivial
        """One-time initialization before loop starts."""
        ...

    def process(self, snap: SummarySnapshot) -> None:
        """Consume a snapshot. Should not mutate `snap`.

        Exceptions should be raised; the loop wrapper will catch and classify.
        """
        ...

    def teardown(self) -> None:  # pragma: no cover - trivial
        """Cleanup resources (files, threads)."""
        ...

class TerminalRenderer(OutputPlugin):  # Phase 1 rich integration
    name = "terminal"
    # Instance dicts used for timing metrics
    _panel_timing_ns: dict[str, int]
    _panel_timing_calls: dict[str, int]

    def __init__(self, rich_enabled: bool = True, *, compact: bool = False, low_contrast: bool = False, status_file: str | None = None, metrics_url: str | None = None) -> None:
        self._rich = rich_enabled
        self._compact = compact
        self._low_contrast = low_contrast
        self._status_file = status_file or "data/runtime_status.json"
        self._metrics_url = metrics_url
        self._layout = None
        self._live = None
        self._console = None
        # Phase 3: per-panel diff hashing (rich selective updates)
        self._panel_hashes: dict[str,str] | None = None
        # Centralized config: prefer SummaryEnv parsed boolean; fallback to direct env read if loader fails
        try:
            from scripts.summary.env_config import (
                load_summary_env,  # local import to avoid heavy startup cost if unused
            )
            try:
                _env = load_summary_env()
                self._rich_diff_enabled = bool(getattr(_env, "rich_diff_demo_enabled", False))
            except Exception:  # pragma: no cover - defensive; fallback preserves legacy behavior
                self._rich_diff_enabled = os.getenv("G6_SUMMARY_RICH_DIFF", "0").lower() in {"1","true","yes","on"}
        except Exception:  # pragma: no cover - extremely defensive catch (import path issues)
            self._rich_diff_enabled = os.getenv("G6_SUMMARY_RICH_DIFF", "0").lower() in {"1","true","yes","on"}
        # Phase 4 metrics: diff statistics
        self._diff_total_cycles = 0
        self._diff_unchanged_cycles = 0
        self._diff_total_panel_updates = 0
        self._diff_panel_update_hist: list[int] = []  # small running log of counts per cycle
        # Phase 4 metrics: per-panel timing aggregates
        self._panel_timing_ns = {}
        self._panel_timing_calls = {}

    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover - minimal side effects
        logger.debug("TerminalRenderer setup (rich=%s)", self._rich)
        if not self._rich:
            return
        try:
            from rich.console import Console  # type: ignore
            from rich.live import Live  # type: ignore

            from scripts.summary.layout import build_layout  # lazy import
            self._console = Console(force_terminal=True)
            status: dict[str, Any] = {}  # initial empty; first cycle will refresh
            self._layout = build_layout(status, self._status_file, self._metrics_url, compact=self._compact, low_contrast=self._low_contrast)
            self._live = Live(self._layout, console=self._console, refresh_per_second=8, screen=False)
            self._live.__enter__()  # start live context
        except Exception as e:  # noqa: BLE001
            logger.warning("TerminalRenderer rich init failed; falling back to debug logging: %s", e)
            self._rich = False

    def process(self, snap: SummarySnapshot) -> None:  # pragma: no cover - structure only
        try:
            # We separate 'rendering' (rich UI) from 'diff + metrics' so tests can exercise metrics with rich disabled.
            perform_render = self._rich  # original behavior flag
            # Hard override: if explicit env variable is truthy force-enable diff even if SummaryEnv disabled it.
            if os.getenv("G6_SUMMARY_RICH_DIFF", "").lower() in {"1","true","yes","on"} and not self._rich_diff_enabled:
                self._rich_diff_enabled = True
            # Plain mode fast path still logs but can optionally compute diff metrics if rich diff enabled.
            if not perform_render and not self._rich_diff_enabled:
                logger.debug("[terminal/plain] cycle=%s indices=%s alerts=%s", snap.cycle, snap.derived.get("indices_count"), snap.derived.get("alerts_total"))
                return
            from scripts.summary.layout import refresh_layout, update_single_panel  # type: ignore
            if perform_render and self._layout is None:
                return
            status_obj = dict(snap.status) if isinstance(snap.status, Mapping) else None
            # If diff not enabled: full refresh only if rendering; plain mode w/out diff just returns (handled above)
            if not self._rich_diff_enabled:
                if perform_render:
                    refresh_layout(self._layout, status_obj, self._status_file, self._metrics_url, compact=self._compact, low_contrast=self._low_contrast)
                return
            # Centralized hashes: expect loop-populated snap.panel_hashes
            hashes = snap.panel_hashes
            if hashes is None:
                # Fallback: disable diff mode and perform full refresh this cycle
                logger.debug("[terminal] panel_hashes missing; disabling rich diff for session")
                self._rich_diff_enabled = False
                if perform_render:
                    refresh_layout(self._layout, status_obj, self._status_file, self._metrics_url, compact=self._compact, low_contrast=self._low_contrast)
                return
            # First cycle (no baseline) => full refresh + store
            if self._panel_hashes is None:
                # Re-evaluate diff enable flag on first cycle in case environment changed between tests (avoids stale cached value)
                try:
                    from scripts.summary.env_config import load_summary_env  # local import
                    try:
                        _env2 = load_summary_env(force_reload=True)  # type: ignore[call-arg]
                        self._rich_diff_enabled = bool(getattr(_env2, "rich_diff_demo_enabled", self._rich_diff_enabled))
                    except TypeError:
                        # Older loader without force_reload parameter
                        _env2 = load_summary_env()  # type: ignore[misc]
                        self._rich_diff_enabled = bool(getattr(_env2, "rich_diff_demo_enabled", self._rich_diff_enabled))
                except Exception:
                    pass
                if perform_render:
                    refresh_layout(self._layout, status_obj, self._status_file, self._metrics_url, compact=self._compact, low_contrast=self._low_contrast)
                self._panel_hashes = dict(hashes)
                if os.getenv('G6_SUMMARY_DIFF_DEBUG','') not in ('','0','false','no','off'):
                    try:
                        print(f"[summary-diff-debug] baseline_set panels={sorted(hashes.keys())} enabled={self._rich_diff_enabled}")
                    except Exception:
                        pass
                # Metrics init
                self._diff_total_cycles = 1
                self._diff_panel_update_hist.append(len(hashes))
                self._diff_total_panel_updates += len(hashes)
                # Ensure per-panel update counters (with labels) exist deterministically so later
                # diff cycles (or assertions) do not observe a missing label due to order effects.
                # We perform a zero increment which registers the label set without affecting counts.
                try:  # local import guarded; zero-inc pattern mirrors prometheus_client behaviour
                    from scripts.summary import summary_metrics as _sm  # type: ignore
                    for _k in hashes.keys():
                        try:
                            _sm.panel_updates_total.labels(panel=_k).inc(0.0)  # seed label
                        except Exception:
                            pass
                except Exception:
                    pass
                return
            # Determine changed panels
            changed = [k for k,v in hashes.items() if self._panel_hashes.get(k) != v]
            # Defensive: if counters were externally reset between cycles (e.g. metrics registry reset
            # in another fixture), re-seed zero-value label series so downstream assertions do not flake.
            try:
                from scripts.summary import summary_metrics as _sm  # local import
                if changed and not any(k[0] == 'g6_summary_panel_updates_total' for k in _sm._counter_store.keys()):  # type: ignore[attr-defined]
                    for _k in self._panel_hashes.keys():
                        try:
                            _sm.panel_updates_total.labels(panel=_k).inc(0.0)
                        except Exception:
                            pass
            except Exception:
                pass
            if os.getenv('G6_SUMMARY_DIFF_DEBUG','') not in ('','0','false','no','off'):
                try:
                    print(f"[summary-diff-debug] cycle={snap.cycle} changed={changed} prev_keys={sorted(self._panel_hashes.keys())}")
                except Exception:
                    pass
            self._diff_total_cycles += 1
            if not changed:
                self._diff_unchanged_cycles += 1
            if not changed:
                logger.debug("[terminal] cycle=%s no panel changes (rich diff)", snap.cycle)
                if isinstance(status_obj, dict):
                    status_obj.setdefault("panel_push_meta", {})["diff_stats"] = self._render_diff_stats()
                return
            # Metrics increment (single path). Increment once here so counters exist prior to any
            # rendering or potential fallback full refresh. Previously we also incremented after
            # rendering which risked double counting under certain failure interleavings.
            try:
                from scripts.summary import summary_metrics as _sm  # local import
                for key in changed:
                    _sm.panel_updates_total.labels(panel=key).inc()
            except Exception:
                pass
            if perform_render:
                for key in changed:
                    try:
                        import time as _t
                        _start = _t.perf_counter_ns()
                        update_single_panel(self._layout, key, status_obj, self._status_file, self._metrics_url, compact=self._compact, low_contrast=self._low_contrast)
                        _dur = _t.perf_counter_ns() - _start
                        self._panel_timing_ns[key] = self._panel_timing_ns.get(key, 0) + _dur
                        self._panel_timing_calls[key] = self._panel_timing_calls.get(key, 0) + 1
                        try:  # Metrics only if rendering to observe timing
                            from scripts.summary import summary_metrics as _sm  # local import
                            _sm.panel_render_seconds_hist.labels(panel=key).observe(_dur / 1_000_000_000)
                        except Exception:
                            pass
                    except Exception as e:  # noqa: BLE001
                        logger.debug("[terminal] panel update failed; falling back full refresh key=%s err=%s", key, e)
                        if perform_render:
                            refresh_layout(self._layout, status_obj, self._status_file, self._metrics_url, compact=self._compact, low_contrast=self._low_contrast)
                        self._panel_hashes = dict(hashes)
                        self._diff_panel_update_hist.append(len(hashes))
                        self._diff_total_panel_updates += len(hashes)
                        return
            for key in changed:
                self._panel_hashes[key] = hashes[key]
            self._diff_total_panel_updates += len(changed)
            self._diff_panel_update_hist.append(len(changed))
            if len(self._diff_panel_update_hist) > 50:
                self._diff_panel_update_hist = self._diff_panel_update_hist[-50:]
            if isinstance(status_obj, dict):
                meta = status_obj.setdefault("panel_push_meta", {})
                meta["diff_stats"] = self._render_diff_stats()
                meta["timing"] = self._render_panel_timing()
            # Cycle-level metrics update (hit ratio + last updates)
            try:
                from scripts.summary import summary_metrics as _sm
                stats = self._render_diff_stats()
                _sm.diff_hit_ratio_gauge.set(stats["hit_ratio"])  # already rounded
                _sm.panel_updates_last_gauge.set(len(changed))
                total_panels = len(hashes)
                _sm.record_churn(len(changed), total_panels)
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            logger.warning("TerminalRenderer process error: %s", e)

    def _render_diff_stats(self) -> dict[str, Any]:  # pragma: no cover - simple formatting
        total_cycles = max(self._diff_total_cycles, 1)
        hit_ratio = (self._diff_unchanged_cycles / total_cycles) if total_cycles else 0.0
        avg_updates = (self._diff_total_panel_updates / total_cycles) if total_cycles else 0.0
        last = self._diff_panel_update_hist[-1] if self._diff_panel_update_hist else None
        return {
            "cycles": total_cycles,
            "unchanged_cycles": self._diff_unchanged_cycles,
            "hit_ratio": round(hit_ratio, 4),
            "total_panel_updates": self._diff_total_panel_updates,
            "avg_updates_per_cycle": round(avg_updates, 3),
            "last_cycle_updates": last,
        }

    def _render_panel_timing(self) -> dict[str, Any]:  # pragma: no cover - simple formatting
        out: dict[str, Any] = {}
        for k, total_ns in self._panel_timing_ns.items():
            calls = self._panel_timing_calls.get(k, 0)
            avg_ns = total_ns / calls if calls else 0
            out[k] = {
                "calls": calls,
                "total_ms": round(total_ns / 1_000_000, 3),
                "avg_ms": round(avg_ns / 1_000_000, 3),
            }
        return out

    def teardown(self) -> None:  # pragma: no cover
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
        logger.debug("TerminalRenderer teardown")

class PanelsWriter(OutputPlugin):  # placeholder + minimal JSON artifact writer
    name = "panels_writer"

    def __init__(self, panels_dir: str) -> None:
        self._dir = panels_dir
        # Track last cycle content hashes to compute change deltas (file-level diff)
        self._last_hashes: dict[str, str] | None = None
        # Expanded mode can be disabled via env to reduce IO in constrained environments
        import os as _os
        # Centralize via SummaryEnv extension: fallback to direct env read while migration stabilizes
        try:
            from scripts.summary.env_config import load_summary_env  # local import
            try:
                _env = load_summary_env()
                # If future field added (panels_writer_basic), prefer it; else fallback to env
                _basic_cfg = getattr(_env, "panels_writer_basic", None)
                if _basic_cfg is None:
                    basic_flag = _os.getenv("G6_PANELS_WRITER_BASIC", "0").lower() in {"1","true","yes","on"}
                else:
                    basic_flag = bool(_basic_cfg)
            except Exception:  # pragma: no cover
                basic_flag = _os.getenv("G6_PANELS_WRITER_BASIC", "0").lower() in {"1","true","yes","on"}
        except Exception:  # pragma: no cover
            basic_flag = _os.getenv("G6_PANELS_WRITER_BASIC", "0").lower() in {"1","true","yes","on"}
        self._expanded = not basic_flag  # if basic flag set, only unified_snapshot.json
        # Lazy import to avoid cost if validation disabled
        self._validate_fn = None
        try:  # defer import; if module missing or jsonschema absent we ignore
            from src.panels.validate import runtime_validate_panel  # type: ignore
            self._validate_fn = runtime_validate_panel
        except Exception:  # pragma: no cover
            self._validate_fn = None

    def setup(self, context: Mapping[str, Any]) -> None:
        logger.debug("PanelsWriter setup dir=%s", self._dir)

    def process(self, snap: SummarySnapshot) -> None:  # pragma: no cover - minimal write
        # TODO(migration:model-phase2): When UnifiedStatusSnapshot is emitted by the loop,
        # accept it directly (e.g., snap.model) to avoid re-deriving panel payloads from raw dicts.
        # This will enable richer provenance + hashing consistency without extra parsing.
        try:
            os.makedirs(self._dir, exist_ok=True)
        except Exception:
            return
        # Prefer domain snapshot fields when available (Phase 2 migration)
        if getattr(snap, 'domain', None) is not None:
            d = snap.domain  # type: ignore[attr-defined]
            indices_count = d.coverage.indices_count if d and d.coverage else snap.derived.get("indices_count")
            alerts_total = d.alerts.total if d and d.alerts else snap.derived.get("alerts_total")
        else:
            indices_count = snap.derived.get("indices_count")
            alerts_total = snap.derived.get("alerts_total")
        base_payload = {
            "cycle": snap.cycle,
            "ts_built": snap.ts_built,
            "indices_count": indices_count,
            "alerts_total": alerts_total,
            "errors": list(snap.errors),
        }
        # Always write the unified_snapshot summary (stable contract)
        self._write_json("unified_snapshot.json", base_payload)
        if not self._expanded:
            logger.debug("[panels_writer] cycle=%s wrote base snapshot only", snap.cycle)
            return
        # Derive panel-like artifacts from status (best-effort); emulate legacy names subset
        status = snap.status if isinstance(snap.status, Mapping) else {}
        panels = self._extract_panels(status)
        # Wrap each panel payload to conform to generic panel schema (updated_at + data wrapper)
        # The schema requires at minimum an object with 'updated_at' field.
        import datetime as _dt
        try:
            # Use timezone-aware API (py311+) to avoid deprecated utcnow usage
            now_iso = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
        except AttributeError:  # pragma: no cover - fallback for older runtimes
            now_iso = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
        for name, payload in panels.items():
            # If payload already appears to be an envelope (meta + version keys), write as-is.
            if isinstance(payload, dict) and 'meta' in payload and 'version' in payload and 'data' in payload:
                # Optionally validate existing envelope wrapper
                wrapped = payload
            else:
                base_name = name[:-5] if name.endswith('.json') else name
                wrapped = {
                    "panel": base_name,
                    "updated_at": now_iso,
                    "data": payload if payload is not None else None,
                }
            if self._validate_fn:
                try:
                    mode = os.getenv("G6_PANELS_VALIDATE", "warn").lower()
                except Exception:
                    mode = "warn"
                if mode == "strict" and "updated_at" not in wrapped:
                    raise ValueError("runtime panel validation failed: missing 'updated_at'")
                try:
                    self._validate_fn(wrapped)
                except Exception:
                    raise
                if mode == "strict" and "updated_at" not in wrapped:
                    raise ValueError("runtime panel validation failed: missing 'updated_at'")
            self._write_json(name, wrapped)
        # Write manifest summarizing produced artifacts (excluding unified_snapshot.json)
        import hashlib as _hashlib
        import json as _json
        hashes: dict[str,str] = {}
        for fname in panels.keys():
            try:
                # Reconstruct path and load just-written file to hash canonical 'data' portion deterministically
                path = os.path.join(self._dir, fname)
                with open(path, encoding='utf-8') as _f:
                    obj = _json.load(_f)
                data_obj = obj.get('data')
                # Canonicalize via sorted keys JSON (ensure deterministic) then hash
                canon = _json.dumps(data_obj, sort_keys=True, separators=(',',':')).encode('utf-8') if data_obj is not None else b'null'
                digest = _hashlib.sha256(canon).hexdigest()
                hashes[fname] = digest
            except Exception:
                # Omit on failure (best-effort); could log at debug
                continue
        # Emit panel file update metrics (hash diff) – skip first baseline cycle
        try:
            if hashes:
                from scripts.summary import summary_metrics as _sm  # local import
                if self._last_hashes is not None:
                    changed = [k for k,v in hashes.items() if self._last_hashes.get(k) != v]
                    # Increment per changed panel (panel label excludes .json suffix for consistency with terminal metrics)
                    for fname in changed:
                        base = fname[:-5] if fname.endswith('.json') else fname
                        _sm.panel_file_updates_total.labels(panel=base).inc()
                    # Gauge tracks number of changed files this cycle
                    try:
                        _sm.panel_file_updates_last_gauge.set(float(len(changed)))
                    except Exception:
                        pass
                self._last_hashes = dict(hashes)
        except Exception:
            pass
        manifest = {
            "schema_version": 1,
            "generator": "PanelsWriter",
            "cycle": snap.cycle,
            "ts": snap.ts_built,
            "files": sorted(list(panels.keys())),
            # Prefer earlier resolved domain-derived values (indices_count / alerts_total)
            # falling back to derived map only if our locals are None. This fixes a bug where
            # manifest.json could contain null for these fields despite unified_snapshot.json
            # having concrete integers.
            "indices_count": (
                indices_count
                if isinstance(indices_count, int)
                else (
                    snap.derived.get("indices_count")
                    if isinstance(snap.derived.get("indices_count"), int)
                    else (
                        # Final fallback: infer from indices_panel payload if present
                        # Envelope-only mode primary; fallback legacy key for transitional compat
                        (panels.get("indices_panel_enveloped.json", {}).get("data", {}) or {}).get("count")
                    )
                )
            ),
            "alerts_total": (
                alerts_total
                if isinstance(alerts_total, int)
                else (
                    snap.derived.get("alerts_total")
                    if isinstance(snap.derived.get("alerts_total"), int)
                    else (
                        # Fallback: derive from alerts panel length
                        len(panels.get("alerts_enveloped.json", {}).get("data", [])) if isinstance(panels.get("alerts_enveloped.json"), dict) else None
                    )
                )
            ),
            "hashes": hashes if hashes else None,
        }
        # Optional application version (if status.app.version present)
        try:
            app_obj = status.get("app") if isinstance(status, Mapping) else None
            if isinstance(app_obj, Mapping):
                v = app_obj.get("version")
                if isinstance(v, (str, int, float)):
                    manifest["app_version"] = str(v)
        except Exception:  # pragma: no cover - defensive
            pass
        import time as _t
        _t0 = _t.time()
        self._write_json("manifest.json", manifest)
        total_panels = len(panels)
        if os.getenv("G6_SUMMARY_DIAG_TIMING") == "1":
            print(f"[summary-diag] panels_writer cycle={snap.cycle} panels={total_panels} write_manifest_dur={_t.time()-_t0:0.4f}s")
        logger.debug("[panels_writer] cycle=%s wrote %s panel files (+manifest)", snap.cycle, total_panels)

    def teardown(self) -> None:
        logger.debug("PanelsWriter teardown")

    # --- internal helpers -------------------------------------------------
    def _write_json(self, filename: str, payload: Any) -> None:
        path = os.path.join(self._dir, filename)
        try:
            from src.utils.output import atomic_write_json  # type: ignore
            atomic_write_json(path, payload, ensure_ascii=False, indent=2)
            return
        except Exception:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def _extract_panels(self, status: Mapping[str, Any]) -> dict[str, Any]:
        """Map current status fields into panel JSON payloads (best-effort).

        This is a lightweight adapter; as unified snapshot evolves we may shift
        to building panels from the richer internal frame instead of raw status.
        """
        panels: dict[str, Any] = {}
        legacy_compat = os.getenv('G6_PANELS_LEGACY_COMPAT','0').lower() in ('1','true','yes','on')

        def _envelope(name: str, data: Any, source: str = 'summary') -> dict[str, Any]:
            """Build envelope structure for panel output."""
            import datetime as _dt
            import hashlib
            import json
            import time
            # Data should be JSON-serializable; hash only data portion for cache busting
            try:
                raw = json.dumps(data, sort_keys=True, separators=(',',':')) if data is not None else '{}'
            except Exception:
                raw = '{}'
            h = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]
            # Use timezone-aware clock only (avoid utcnow per style guidelines)
            updated = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
            return {
                'panel': name,
                'version': 1,
                'generated_at': int(time.time()),
                'updated_at': updated,
                'data': data,
                'meta': { 'source': source, 'schema': 'v1', 'hash': h }
            }
        # indices panel
        try:
            raw_id = status.get("indices_detail")
            indices_detail: Mapping[str, Any] = raw_id if isinstance(raw_id, Mapping) else {}
            items: list[dict[str, Any]] = []
            for name, data in indices_detail.items():
                if not isinstance(data, Mapping):
                    continue
                dq = None
                dq_obj = data.get("dq")
                if isinstance(dq_obj, Mapping):
                    dq = dq_obj.get("score_percent")
                items.append({
                    "index": name,
                    "status": data.get("status"),
                    "dq_score": dq,
                    "age": data.get("age") or data.get("age_sec"),
                })
            data_obj = {"items": items, "count": len(items)}
            panels["indices_panel_enveloped.json"] = _envelope('indices_panel', data_obj)
            if legacy_compat:
                panels["indices_panel.json"] = data_obj
            # Phase 4: StreamGater always active; baseline indices_stream.json emission permanently delegated.
            # If retired flags are set, log a one-time warning.
            # (Phase 4) Note: Retired flag warnings centralized in StreamGaterPlugin; no emission here to avoid duplicates.
        except Exception:
            pass
        # alerts panel
        try:
            raw_alerts = []
            for key in ("alerts", "events"):
                val = status.get(key)
                if isinstance(val, list):
                    raw_alerts.extend([a for a in val if isinstance(a, Mapping)])
            panels["alerts_enveloped.json"] = _envelope('alerts', raw_alerts)
            if legacy_compat:
                panels["alerts.json"] = raw_alerts
        except Exception:
            pass
        # memory / system panel (simplified)
        try:
            mem_obj = status.get("memory")
            mem = mem_obj if isinstance(mem_obj, Mapping) else {}
            loop_obj = status.get("loop")
            loop = loop_obj if isinstance(loop_obj, Mapping) else {}
            sys_obj = {
                "memory_rss_mb": mem.get("rss_mb") or mem.get("rss"),
                "cycle": loop.get("cycle"),
                "last_duration": loop.get("last_duration"),
                "interval": status.get("interval") or loop.get("target_interval"),
            }
            panels["system_enveloped.json"] = _envelope('system', sys_obj)
            if legacy_compat:
                panels["system.json"] = sys_obj
        except Exception:
            pass
        # performance / metrics panel (placeholder extraction)
        try:
            perf = status.get("performance") if isinstance(status.get("performance"), Mapping) else {}
            perf_obj = {k: v for k, v in perf.items()} if perf else {}
            panels["performance_enveloped.json"] = _envelope('performance', perf_obj)
            if legacy_compat:
                panels["performance.json"] = perf_obj
        except Exception:
            pass
        # analytics panel (very shallow placeholder based on hypothetical aggregations)
        try:
            analytics = status.get("analytics") if isinstance(status.get("analytics"), Mapping) else {}
            analytics_obj = {k: v for k, v in analytics.items()} if analytics else {}
            panels["analytics_enveloped.json"] = _envelope('analytics', analytics_obj)
            if legacy_compat:
                panels["analytics.json"] = analytics_obj
        except Exception:
            pass
        # links panel (static best-effort)
        try:
            app = status.get("app") if isinstance(status.get("app"), Mapping) else {}
            version = app.get("version") if isinstance(app, Mapping) else None
            links_obj = {
                "metrics_url": os.getenv("G6_METRICS_URL") or None,
                "version": version,
            }
            panels["links_enveloped.json"] = _envelope('links', links_obj)
            if legacy_compat:
                panels["links.json"] = links_obj
        except Exception:
            pass
        return panels

class MetricsEmitter(OutputPlugin):  # placeholder
    """Best-effort Prometheus metrics publisher for unified loop.

    Metrics are gated behind environment variable `G6_UNIFIED_METRICS` (default off)
    to avoid cardinality / overhead surprises during early rollout.

    Exported metric families (names tentative – kept separate from legacy cycle metrics):

    - g6_unified_cycle_total (Counter) – total cycles executed by unified loop
    - g6_unified_cycle_duration_seconds (Histogram) – wall clock per loop iteration
    - g6_unified_snapshot_build_seconds (Histogram) – snapshot builder duration
    - g6_unified_render_seconds (Histogram, label plugin="terminal") – render/update duration (if measurable)
    - g6_unified_panels_write_seconds (Histogram, plugin="panels_writer") – panel write duration
    - g6_unified_plugin_exceptions_total (Counter, label plugin) – plugin raised exceptions (caught by loop)
    - g6_unified_conflict_detected (Gauge) – 1 when legacy bridge conflict detected (optional external set)
    - g6_unified_last_cycle_timestamp (Gauge) – unix ts of last completed cycle
    - g6_unified_errors_total (Counter) – snapshot build errors accumulated

    This plugin does not itself measure per-plugin durations; the loop can inject
    timing hints via a lightweight side-channel in future. For now we opportunistically
    measure wall time around process() for known plugins when attribute hints present.
    """
    name = "metrics"

    def __init__(self) -> None:
        self._enabled = False
        self._families: dict[str, Any] = {}
        self._have_prom = False

    def _register(self) -> None:
        try:  # lazy import; tolerate missing dependency
            from prometheus_client import Counter, Gauge, Histogram  # type: ignore
        except Exception:  # noqa: BLE001
            logger.info("MetricsEmitter disabled (prometheus_client not available)")
            return
        self._have_prom = True
        # Histogram buckets tuned for sub-second to multi-second cycles
        buckets = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
        self._families["cycle_total"] = Counter("g6_unified_cycle_total", "Unified loop cycles executed")
        self._families["cycle_dur"] = Histogram("g6_unified_cycle_duration_seconds", "Unified loop cycle duration", buckets=buckets)
        self._families["build_dur"] = Histogram("g6_unified_snapshot_build_seconds", "Snapshot build duration", buckets=buckets)
        self._families["plugin_dur"] = Histogram("g6_unified_plugin_process_seconds", "Plugin process duration", ["plugin"], buckets=buckets)
        self._families["plugin_ex"] = Counter("g6_unified_plugin_exceptions_total", "Plugin process exceptions", ["plugin"])
        self._families["panels_write_dur"] = Histogram("g6_unified_panels_write_seconds", "Panels writer duration", buckets=buckets)
        self._families["render_dur"] = Histogram("g6_unified_render_seconds", "Terminal render duration", buckets=buckets)
        self._families["conflict"] = Gauge("g6_unified_conflict_detected", "1 when legacy panels bridge conflict detected")
        self._families["last_ts"] = Gauge("g6_unified_last_cycle_timestamp", "Last unified cycle completion timestamp")
        self._families["errors_total"] = Counter("g6_unified_errors_total", "Total snapshot build errors")
        # SSE metrics families (lazy observed if SSE enabled)
        self._families["sse_events_total"] = Counter("g6_sse_events_total", "Total SSE events emitted")
        self._families["sse_full_snapshots"] = Counter("g6_sse_full_snapshots_total", "Total SSE full_snapshot events")
        self._families["sse_panel_updates"] = Counter("g6_sse_panel_updates_total", "Total SSE panel_update events")
        self._families["sse_heartbeats"] = Counter("g6_sse_heartbeats_total", "Total SSE heartbeat events")
        self._families["sse_errors"] = Counter("g6_sse_errors_total", "Total SSE error events")
        logger.debug("MetricsEmitter Prometheus families registered")

    def setup(self, context: Mapping[str, Any]) -> None:  # pragma: no cover - trivial
        import os
        if os.getenv("G6_UNIFIED_METRICS", "0") not in ("1", "true", "on", "yes"):  # simple gate
            return
        self._enabled = True
        self._register()

    # External helpers (optional usage by loop)
    def mark_conflict(self) -> None:
        fam = self._families.get("conflict")
        try:
            if fam:  # type: ignore[truthy-function]
                fam.set(1)  # type: ignore[attr-defined]
        except Exception:
            pass

    def clear_conflict(self) -> None:
        fam = self._families.get("conflict")
        try:
            if fam:
                fam.set(0)  # type: ignore[attr-defined]
        except Exception:
            pass

    def observe_cycle(self, cycle_duration: float, build_duration: float, errors: int) -> None:
        if not self._enabled or not self._have_prom:
            return
        try:
            self._families["cycle_total"].inc()  # type: ignore[attr-defined]
            self._families["cycle_dur"].observe(cycle_duration)  # type: ignore[attr-defined]
            self._families["build_dur"].observe(build_duration)  # type: ignore[attr-defined]
            if errors:
                self._families["errors_total"].inc(errors)  # type: ignore[attr-defined]
            self._families["last_ts"].set(time.time())  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            pass

    def observe_sse_metrics(self, sse_metrics: Mapping[str,int]) -> None:
        if not self._enabled or not self._have_prom:
            return
        try:
            # We increment counters by delta between provided value and last seen; store last seen in object.
            prev = getattr(self, '_sse_prev', {}) or {}
            deltas = {}
            for k in ("events_total","full_snapshots","panel_updates","heartbeats","errors"):
                v = int(sse_metrics.get(k, 0))
                pv = int(prev.get(k, 0))
                if v > pv:
                    deltas[k] = v - pv
            # update prev snapshot
            self._sse_prev = {k:int(sse_metrics.get(k,0)) for k in ("events_total","full_snapshots","panel_updates","heartbeats","errors")}
            fam_map = {
                'events_total': 'sse_events_total',
                'full_snapshots': 'sse_full_snapshots',
                'panel_updates': 'sse_panel_updates',
                'heartbeats': 'sse_heartbeats',
                'errors': 'sse_errors',
            }
            for k, delta in deltas.items():
                fam = self._families.get(fam_map[k])
                if fam and delta > 0:
                    fam.inc(delta)  # type: ignore[attr-defined]
        except Exception:
            pass

    def observe_plugin(self, plugin: str, duration: float, had_error: bool) -> None:
        if not self._enabled or not self._have_prom:
            return
        try:
            self._families["plugin_dur"].labels(plugin=plugin).observe(duration)  # type: ignore[attr-defined]
            if had_error:
                self._families["plugin_ex"].labels(plugin=plugin).inc()  # type: ignore[attr-defined]
            if plugin == "panels_writer":
                self._families["panels_write_dur"].observe(duration)  # type: ignore[attr-defined]
            elif plugin == "terminal":
                self._families["render_dur"].observe(duration)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

    def process(self, snap: SummarySnapshot) -> None:  # pragma: no cover - plugin does not emit per-cycle by itself
        # Work performed externally via observe_* hooks; keep interface symmetry.
        return

    def teardown(self) -> None:  # pragma: no cover - trivial
        # No explicit shutdown API in prometheus_client
        logger.debug("MetricsEmitter teardown (enabled=%s)", self._enabled)
