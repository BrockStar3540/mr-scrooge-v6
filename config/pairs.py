from dataclasses import dataclass, field

PIP = {
    "AUD_JPY": 0.01, "EUR_JPY": 0.01, "USD_JPY": 0.01,
    "AUD_USD": 0.0001, "EUR_USD": 0.0001, "GBP_USD": 0.0001,
    "USD_CAD": 0.0001, "USD_CHF": 0.0001,
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
}
