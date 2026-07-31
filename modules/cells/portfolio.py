"""modules/cells/portfolio.py — cell-era portfolio selection (Phase D).

Pure risk arithmetic over CellIntents — NO alpha logic lives here. The cell
decides IF and WHICH SIDE; this layer only decides whether the book can take
the trade right now. Caps preserved verbatim from the playmaker era:

  - one position per pair
  - max_concurrent_trades          (playmaker_config.json account block)
  - max_per_currency_direction     (same-sign legs per currency)
  - spread fail-closed             (playmaker _MAX_SPREAD table; <=0 = bad tick)
  - post-loss cooldown per pair    (60 min after a losing exit)

Among survivors, prefer the highest measured ev_seq (evidence, not a score);
ties broken by earliest pair name for determinism.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from modules.playmaker.playmaker import (pm_max_concurrent,
                                          pm_max_per_currency_direction,
                                          _MAX_SPREAD, _DEFAULT_MAX_SPREAD)

log = logging.getLogger("v5.cells.portfolio")

_COOLDOWN_MIN = 60  # minutes after a losing exit before the pair may re-enter


def _currency_legs(open_positions: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """(currency, sign) -> concurrent leg count. sign: 'long'|'short' exposure
    of that currency. A long AAA_BBB is long AAA and short BBB."""
    legs: dict[tuple[str, str], int] = {}
    for pair, direction in open_positions:
        try:
            base, quote = pair.split("_")
        except ValueError:
            continue
        if direction == "long":
            exposures = ((base, "long"), (quote, "short"))
        else:
            exposures = ((base, "short"), (quote, "long"))
        for key in exposures:
            legs[key] = legs.get(key, 0) + 1
    return legs


def select_intent(intents: list,
                  open_pairs: set,
                  open_positions: list[tuple[str, str]],
                  views: list,
                  sl_history: dict,
                  now: datetime) -> Optional[object]:
    """Return the best cap-passing CellIntent, or None.

    Call repeatedly (excluding already-opened pairs) for multi-open cycles —
    each call re-derives currency exposure from the caller's updated
    open_positions, exactly like the pick_best loop did.
    """
    if not intents:
        return None
    if len(open_pairs) >= pm_max_concurrent():
        return None

    legs = _currency_legs(open_positions)
    max_ccy = pm_max_per_currency_direction()

    candidates = []
    for it in intents:
        if it.pair in open_pairs:
            continue

        # Post-loss cooldown
        last_loss = sl_history.get(it.pair)
        if last_loss is not None and (now - last_loss) < timedelta(minutes=_COOLDOWN_MIN):
            continue

        # Spread fail-closed: <=0 means bid==ask / bad tick — never trade it
        view = next((v for v in views if v.pair == it.pair), None)
        spread = getattr(view, "spread_pips", 0.0) if view is not None else 0.0
        if spread <= 0.0 or spread > _MAX_SPREAD.get(it.pair, _DEFAULT_MAX_SPREAD):
            continue

        # Per-currency directional cap
        try:
            base, quote = it.pair.split("_")
        except ValueError:
            continue
        if it.side == "long":
            new_legs = ((base, "long"), (quote, "short"))
        else:
            new_legs = ((base, "short"), (quote, "long"))
        if any(legs.get(k, 0) + 1 > max_ccy for k in new_legs):
            log.info("CELLSKIP %s/%s setup=%s reason=currency_cap", it.pair, it.session,
                     getattr(it, "setup_id", "?"))
            continue

        candidates.append(it)

    if not candidates:
        return None
    # SELECTOR (charter, 2026-07-31): ExecutionScore ranking — relative heat
    # + trust floor − correlation penalty − exposure cost — replaces
    # ev_seq-then-alphabetical. Ties (all-zero scores, e.g. no heat file)
    # fall back to the old deterministic order. Every loser is logged with
    # why it lost the seat.
    try:
        from core.execution_score import execution_score, load_heat_scores
        scores = load_heat_scores()
        open_ccy: dict = {}
        for _p2, _ in open_positions:   # currency legs already open
            b, q = _p2.split("_")
            open_ccy[b] = open_ccy.get(b, 0) + 1
            open_ccy[q] = open_ccy.get(q, 0) + 1
        n_open = len(open_pairs)
        _cap = pm_max_concurrent()
        def _xs(i):
            return execution_score(f"{i.pair}|{i.session}|{i.setup_id}",
                                   i.side, i.pair, scores, open_ccy,
                                   n_open, _cap)
        candidates.sort(key=lambda i: (-_xs(i),
                                       -(i.expected.get("ev_seq") or 0.0),
                                       i.pair))
        for lose in candidates[1:]:
            log.info("SELECTOR-X %s/%s setup=%s lost seat to %s/%s setup=%s "
                     "(xs %.3f vs %.3f)", lose.pair, lose.session,
                     lose.setup_id, candidates[0].pair, candidates[0].session,
                     candidates[0].setup_id, _xs(lose), _xs(candidates[0]))
    except Exception as _se:
        log.warning("SELECTOR-X ranking failed (%s) — ev_seq order kept", _se)
        candidates.sort(key=lambda i: (-(i.expected.get("ev_seq") or 0.0), i.pair))
    return candidates[0]
