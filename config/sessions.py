# Canonical trading-session mapping — SINGLE SOURCE OF TRUTH.
#
# UTC hour -> one of the 3 dm_04 calibration sessions. Everything keys off this:
#   * the feed stamps MarketView.session with coarse_session() (core/feed/oanda.py)
#   * the direction/momentum modules are calibrated per (pair x session) on these labels
#   * the playmaker gates eligibility on these labels (config.pairs.PAIR_SESSIONS)
# Keep PAIR_SESSIONS in lockstep with the labels defined here.

SESSIONS = {
    "asia":   (22, 7),   # 22:00-07:00 UTC  (Tokyo / Sydney)
    "london": (7, 13),   # 07:00-13:00 UTC  (European morning, pre-NY)
    "ny":     (13, 22),  # 13:00-22:00 UTC  (NY open through close)
}


def coarse_session(hour_utc: int) -> str:
    """UTC hour -> 3-session label used in dm_04 calibration."""
    if  7 <= hour_utc < 13: return "london"
    if 13 <= hour_utc < 22: return "ny"
    return "asia"


# Deprecated alias — kept so any stray import returns the ACCURATE coarse session
# instead of the old (removed) fine-grained mapping. Prefer coarse_session().
current_session = coarse_session
