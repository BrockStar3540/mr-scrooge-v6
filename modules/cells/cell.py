"""modules/cells/cell.py — CellModule, CellIntent, ExitParams (Phase C).

§1 interface per CELL_ARCHITECTURE_SPEC.md.  Shadow-only in Phase C:
  CELL_EXECUTION_ENABLED=False → evaluate() always returns None, but
  stamps a CELLSHADOW line for every qualifying setup.

Config loading
--------------
One file per pair: config/cells/<PAIR>.json.
Hot-reload: mtime is checked once per evaluate() call (i.e. once per cycle).
A missing or malformed pair file → pair's cells silently absent until file
arrives (one warning per day per pair).  A parse error → all setups for that
pair disabled; one hourly warning; engine never crashes.

Condition evaluation
--------------------
Each condition resolves from view via getattr(view, feature).  An unreadable
feature (AttributeError / None) skips the SETUP with a once-per-day warning
naming the feature.  Conditions use the "resolved" key for percentile-form;
absolute min/max for the fixed form.  Both forms are OR'd per condition
(only one form may be active in any given condition dict).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("v5.cells")

# Path to per-pair config directory (config/cells/<PAIR>.json)
_CELLS_DIR = Path(__file__).resolve().parents[2] / "config" / "cells"

# ── Phase-C import ────────────────────────────────────────────────────────────
# Import lazily inside evaluate() to allow CELL_EXECUTION_ENABLED to be tested
# at the module level without circular imports.
def _exec_enabled() -> bool:
    from modules.cells import CELL_EXECUTION_ENABLED
    return CELL_EXECUTION_ENABLED


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ExitParams:
    """Per-setup exit geometry.  RatchetManager reads these when not None.

    Exit classes (2026-07-05): mode="bracket" -> BracketManager (server TP/SL
    + timeout, no trail); mode="ratchet" -> RatchetManager. trail_mult>0 makes
    the trail ATR-scaled: trail_pips = clamp(trail_mult*atr_5m, trail_min,
    trail_max), resolved at qualification time (Q2: atr_5m is the distance
    knob, rho 0.4-0.7 in all 24 cells)."""
    sl_pips:      float
    trigger_pips: float
    trail_pips:   float
    mode:             str   = "ratchet"   # "ratchet" | "bracket"
    tp_pips:          float = 0.0         # bracket: server-side limit TP
    timeout_min:      float = 0.0         # bracket: flat after N min (0=off)
    entry_cutoff_utc: float = 0.0         # no new entries at/after this UTC hour (0=off)
    trail_mult:       float = 0.0         # ratchet: ATR-scaled trail (0=fixed)
    trail_min:        float = 0.0
    trail_max:        float = 0.0


@dataclass
class CellIntent:
    """Returned by CellModule.evaluate() when a setup fully qualifies."""
    pair:           str
    session:        str
    side:           str           # "long" | "short" — from the qualifying setup
    setup_id:       str           # config key that fired (for audit)
    horizon_min:    int           # evaluation horizon: 20 | 30 | 60 | 240
    exit_params:    ExitParams
    units_hint:     float         # risk-normalised size (size_modulators applied)
    conds_snapshot: dict          # feature values at qualification time
    expected:       dict          # {ev_seq, wr, lineage} from config
    probe:          bool = False  # PROBE seat: fires at pm_probe_mult sizing


# ── Warning-rate limiters ─────────────────────────────────────────────────────
# last_warn[(pair, "mtime_error" | feature_name)] -> float epoch
_last_warn: dict[tuple, float] = {}

def _should_warn(key: tuple, period_s: float) -> bool:
    """Return True at most once per period_s seconds for a given key."""
    now = time.monotonic()
    if now - _last_warn.get(key, 0.0) >= period_s:
        _last_warn[key] = now
        return True
    return False

_ONE_HOUR  = 3600.0
_ONE_DAY   = 86400.0


# ── Config loader ─────────────────────────────────────────────────────────────

@dataclass
class _LoadedConfig:
    data:  dict       # parsed JSON
    mtime: float      # os.stat mtime at load time
    path:  Path


# pair -> _LoadedConfig | None (None = file absent/malformed)
_config_cache: dict[str, Optional[_LoadedConfig]] = {}
# pair -> mtime at last check (so we only stat once per cycle)
_mtime_cache:  dict[str, float] = {}


def _load_pair_config(pair: str) -> Optional[dict]:
    """Return parsed config dict for *pair*, with hot-reload on mtime change.

    Graceful failures:
      - Missing file  → return None (one info log, no crash; cells absent)
      - Malformed JSON→ return None, one HOURLY warning, disable pair's cells
    """
    path = _CELLS_DIR / f"{pair}.json"

    try:
        st = path.stat()
        cur_mtime = st.st_mtime
    except FileNotFoundError:
        # Absent is expected before Phase B generates them — silent after the
        # first-ever info log (tracked via _config_cache initialisation).
        if pair not in _config_cache:
            log.info("cells: no config for %s (%s absent) — cells absent until file arrives", pair, path.name)
            _config_cache[pair] = None
        return None
    except OSError as exc:
        if _should_warn((pair, "stat_error"), _ONE_HOUR):
            log.warning("cells: cannot stat %s: %s — pair disabled", path, exc)
        _config_cache[pair] = None
        return None

    # Hot-reload: if mtime unchanged and we have a cached result, return it
    cached = _config_cache.get(pair)
    if cached is not None and cached.mtime == cur_mtime:
        return cached.data
    if _mtime_cache.get(pair) == cur_mtime:
        # This exact file version already failed validation — don't re-parse
        # every cycle; serve the retained prior valid config (or nothing).
        return cached.data if cached is not None else None

    # (Re)load — with STRUCTURAL validation and retain-last-valid semantics
    # (review round 2): a malformed hot edit must neither reach the engine NOR
    # dark the pair when a previously-valid config exists. First-ever invalid
    # file -> pair absent (nothing safe to retain).
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        from config.cell_schema import validate_pair_config
        result = validate_pair_config(data, path)
        if not result.ok:
            raise ValueError("schema: " + "; ".join(result.errors[:8]))
        _config_cache[pair] = _LoadedConfig(data=data, mtime=cur_mtime, path=path)
        _mtime_cache[pair]  = cur_mtime
        log.info("cells: loaded config for %s (%d sessions)", pair,
                 len(data.get("sessions", {})))
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        _mtime_cache[pair] = cur_mtime   # remember broken mtime so we don't retry every cycle
        prior = _config_cache.get(pair)
        if _should_warn((pair, "parse_error"), _ONE_HOUR):
            if prior is not None:
                log.warning("cells: INVALID config %s: %s — RETAINING the prior "
                            "valid config (fix the file; hourly reminder)",
                            path.name, exc, )
            else:
                log.warning("cells: malformed config %s: %s — all setups for %s "
                            "disabled (no prior valid config; hourly reminder)",
                            path.name, exc, pair)
        return prior.data if prior is not None else None


# ── Condition evaluator ───────────────────────────────────────────────────────

def _eval_condition(cond: dict, view, pair: str, setup_id: str) -> Optional[bool]:
    """Return True/False if the condition passes/fails, or None if the feature
    is unreadable (triggers a once-per-day skip warning).

    Percentile-form: uses cond["resolved"] = [lo, hi] (generator writes these).
    Absolute form  : uses cond["min"] / cond["max"] (None = no bound).
    """
    feature = cond.get("feature")
    if not feature:
        return None

    val = getattr(view, feature, None)
    if val is None:
        # Also catches fields that default to 0.0 but are genuinely absent — we
        # treat *None* returns as unreadable; 0.0 defaults pass through.
        if _should_warn((pair, setup_id, feature, "unreadable"), _ONE_DAY):
            log.warning(
                "cells: %s setup=%s feature=%s unreadable on MarketView "
                "— setup skipped (once-per-day warning; feed extension may resolve)",
                pair, setup_id, feature,
            )
        return None

    # Percentile-form (canonical for regime-sensitive conditions)
    resolved = cond.get("resolved")
    if resolved is not None:
        lo, hi = float(resolved[0]), float(resolved[1])
        return lo <= float(val) <= hi

    # Absolute form
    lo = cond.get("min")
    hi = cond.get("max")
    if lo is not None and float(val) < float(lo):
        return False
    if hi is not None and float(val) > float(hi):
        return False
    return True


# ── CellModule ────────────────────────────────────────────────────────────────

class CellModule:
    """One instance per (pair × session).  Stateless between cycles.

    Status vocabulary
    -----------------
      ACTIVE    : full candidate; may return intent (when CELL_EXECUTION_ENABLED=True)
      SHADOW    : evaluates + stamps; never returns intent even at Phase D
      SUSPENDED : tripped by a tripwire; treated identically to SHADOW here
                  (suspension logic is enforced by the config generator / monthly refit)
    """

    def __init__(self, pair: str, session: str, config: dict):
        self.pair    = pair
        self.session = session
        # config = the CELLCFG block for this session from the pair JSON
        self._cfg    = config

    def evaluate(self, view, now: datetime) -> Optional[CellIntent]:
        """Evaluate ALL setups in this cell against *view*, then return the
        first qualifying ACTIVE setup as a CellIntent (or None).

        EVERY setup is evaluated and every qualifying setup STAMPS, every
        cycle — an early ACTIVE qualifier no longer short-circuits the loop
        (2026-07-27 external-review fix: the old early return silently starved
        later setups of stamps, biasing the shadow trials by config order —
        and the newest hypotheses always sit last in the list).

        PHASE-C LOCK: CELL_EXECUTION_ENABLED=False forces None regardless of status.
        SHADOW/SUSPENDED setups always return None.

        Side effects: emits CELLSHADOW log lines for every qualifying setup.
        """
        setups = self._cfg.get("setups", [])
        if not setups:
            return None   # NO-SIDE cell — silent
        intent: Optional[CellIntent] = None   # first qualifying ACTIVE, returned after the loop

        for setup in setups:
            status = setup.get("status", "SHADOW")
            side   = setup.get("side")
            if not side:
                continue   # malformed setup; skip silently

            # Evaluate ALL conditions
            conditions   = setup.get("conditions", [])
            snapshot     = {}
            all_pass     = True
            skip_setup   = False

            for cond in conditions:
                result = _eval_condition(cond, view, self.pair, setup.get("id", "?"))
                if result is None:
                    skip_setup = True
                    break
                feature = cond.get("feature", "?")
                snapshot[feature] = getattr(view, feature, None)
                if not result:
                    all_pass = False
                    break

            if skip_setup:
                continue

            if not all_pass:
                continue

            # Setup qualifies — compute expected EV and build snapshot
            evidence    = setup.get("evidence", {})
            ev_seq      = evidence.get("ev_seq", 0.0)
            exit_cfg    = setup.get("exit", {})
            # Entry cutoff (FAST class): no fresh slices at/after cutoff UTC hour
            # — rollover blowout risk outweighs any late-session slice EV.
            _cutoff = float(exit_cfg.get("entry_cutoff_utc", 0.0) or 0.0)
            if _cutoff > 0 and (now.hour + now.minute / 60.0) >= _cutoff:
                log.info("CELL %s/%s setup=%s blocked: entry_cutoff_utc=%.0f",
                         self.pair, self.session, setup.get("id", "?"), _cutoff)
                continue
            exit_params = ExitParams(
                sl_pips      = float(exit_cfg.get("sl_pips", 12.0)),
                trigger_pips = float(exit_cfg.get("trigger_pips", 10.0)),
                trail_pips   = float(exit_cfg.get("trail_pips", 1.5)),
                mode             = str(exit_cfg.get("mode", "ratchet")),
                tp_pips          = float(exit_cfg.get("tp_pips", 0.0) or 0.0),
                timeout_min      = float(exit_cfg.get("timeout_min", 0.0) or 0.0),
                entry_cutoff_utc = _cutoff,
                trail_mult       = float(exit_cfg.get("trail_mult", 0.0) or 0.0),
                trail_min        = float(exit_cfg.get("trail_min", 0.0) or 0.0),
                trail_max        = float(exit_cfg.get("trail_max", 0.0) or 0.0),
            )
            if exit_params.trail_mult > 0:
                _atr = getattr(view, "atr_5m", None)
                if _atr:
                    exit_params.trail_pips = round(max(exit_params.trail_min,
                        min(exit_params.trail_max, exit_params.trail_mult * float(_atr))), 2)

            # Size with modulators
            sizing = setup.get("sizing", {})
            risk_pct  = float(sizing.get("risk_pct", 0.5))
            units_hint = risk_pct  # caller scales to actual units; modulators below

            for mod in sizing.get("size_modulators", []):
                feat_name = mod.get("feature")
                feat_val  = getattr(view, feat_name, None) if feat_name else None
                if feat_val is not None:
                    gte = mod.get("gte")
                    if gte is not None and float(feat_val) >= float(gte):
                        units_hint *= float(mod.get("mult", 1.0))

            # Build compact condition snapshot for logging
            compact = {f: round(v, 5) for f, v in snapshot.items() if v is not None}

            setup_id = setup.get("id", "?")
            _exec    = _exec_enabled()

            # Phase-C: even ACTIVE setups stamp as shadow-mode
            # PROBE (charter, 2026-07-31): a reduced-size audition seat
            # between SHADOW and ACTIVE — fires like ACTIVE, sized down at
            # the engine (pm_probe_mult), generates real broker cycles cheap.
            would_trade = (status in ("ACTIVE", "PROBE") and _exec)
            stamp_status = status
            # If CELL_EXECUTION_ENABLED=False and setup is ACTIVE, stamp shows status=ACTIVE
            # so the scorer can distinguish would-trade stamps.

            # D-6: stamp the live spread — the cost this entry would actually
            # pay — so scoring can judge net-of-cost instead of frictionless
            # mid drift (all parsers tolerate the trailing token).
            _spread = float(getattr(view, "spread_pips", 0.0) or 0.0)
            log.info(
                "CELLSHADOW %s/%s setup=%s side=%s conds=%s exp_ev=%+.3f status=%s spread=%.1f",
                self.pair, self.session,
                setup_id, side,
                compact,
                float(ev_seq or 0.0),
                stamp_status,
                _spread,
            )
            # D-7: the structured, versioned stamp — carries the EXECUTABLE
            # entry + the setup's own exit geometry for shadow-execution
            # scoring. CELLSHADOW stays for legacy consumers.
            try:
                from core.trial_events import make_stamp
                _ts = make_stamp(now=now, pair=self.pair, session=self.session,
                                 setup=setup, status=stamp_status, view=view)
                if _ts is not None:
                    log.info("TRIALSTAMP %s", _ts.to_json())
            except Exception as _tse:
                if _should_warn((self.pair, "trialstamp"), _ONE_HOUR):
                    log.warning("TRIALSTAMP emit failed for %s/%s: %s",
                                self.pair, setup_id, _tse)

            # Capture the FIRST qualifying ACTIVE as the intent — but keep
            # looping so every remaining setup still evaluates and stamps.
            if would_trade and intent is None:
                intent = CellIntent(
                    pair           = self.pair,
                    session        = self.session,
                    probe          = (status == "PROBE"),
                    side           = side,
                    setup_id       = setup_id,
                    horizon_min    = int(setup.get("horizon_min", 60)),
                    exit_params    = exit_params,
                    units_hint     = units_hint,
                    conds_snapshot = compact,
                    expected       = {
                        "ev_seq":  ev_seq,
                        "wr":      evidence.get("wr"),
                        "lineage": evidence.get("source", ""),
                    },
                )
        return intent
