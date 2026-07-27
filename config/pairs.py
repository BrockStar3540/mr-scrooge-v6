from dataclasses import dataclass, field

PIP = {
    "AUD_JPY": 0.01, "EUR_JPY": 0.01, "USD_JPY": 0.01,
    "AUD_USD": 0.0001, "EUR_USD": 0.0001, "GBP_USD": 0.0001,
    "USD_CAD": 0.0001, "USD_CHF": 0.0001,
    # March-2026 replay crosses (2026-07-27, Brock): SHADOW-only cells — in the
    # scan loop for stamps, never playmaker-eligible until promoted by the bar.
    "CAD_JPY": 0.01,
    "AUD_CAD": 0.0001, "EUR_CAD": 0.0001, "GBP_CAD": 0.0001,
    # April-2026 replay CHF crosses (2026-07-27, Brock): same deal — SHADOW-only.
    "CHF_JPY": 0.01,
    "EUR_CHF": 0.0001, "AUD_CHF": 0.0001,
}

PAIRS = list(PIP.keys())

# Session activity map: which sessions each pair is "tier-1" active
PAIR_SESSIONS = {
    "AUD_JPY":  ["asia", "london"],
    "AUD_USD":  ["asia", "london", "ny"],
    "EUR_JPY":  ["asia", "london", "ny"],
    "EUR_USD":  ["asia", "london", "ny"],
    "GBP_USD":  ["asia", "london", "ny"],
    "USD_CAD":  ["asia", "london", "ny"],
    "USD_CHF":  ["london", "ny"],
    "USD_JPY":  ["asia", "london", "ny"],
    # march-replay crosses (SHADOW-only cells; listed for future promotion)
    "CAD_JPY":  ["asia", "london", "ny"],
    "AUD_CAD":  ["asia", "london", "ny"],
    "EUR_CAD":  ["london", "ny"],
    "GBP_CAD":  ["london", "ny"],
    "CHF_JPY":  ["asia", "london", "ny"],
    "EUR_CHF":  ["asia", "london", "ny"],
    "AUD_CHF":  ["asia", "london", "ny"],
}
