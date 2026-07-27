"""core/broker/oanda.py — OANDA REST v3 order execution for V5.

Credentials: OANDA_API_URL, OANDA_API_TOKEN, OANDA_ACCOUNT_ID
Loaded from ~/.openclaw/secrets.env — never stored in code.

Public API:
    broker = OandaBroker()
    trade  = broker.place_market("EUR_USD", "long", units=10000, sl_pips=20)
    broker.close_position(trade["id"])
    nav    = broker.account_nav()
    size   = broker.size_units("EUR_USD", direction, sl_pips=20, risk_pct=0.005)
"""
from __future__ import annotations
import json, logging, os, socket, time, urllib.error, urllib.request
from typing import Optional

from config.pairs import PIP

log = logging.getLogger("v5.broker")

# Hard initial stop placed on OANDA server at trade entry — ultimate fallback
# value used only when exit_config.json is missing/corrupt. The live value
# comes from exit_config.json "initial_sl_pips" (currently 20.0) which is
# hot-reloaded every trade via ratchet._load_config() and overrides this
# constant on every call. Do NOT treat this constant as the operational default.
DEFAULT_INITIAL_SL_PIPS = 12  # ultimate fallback only; overridden by exit_config.json every call
# Default per-trade MARGIN commitment as a fraction of account balance (V1 model).
MARGIN_PCT = 0.005   # fallback when playmaker_config.json missing
RISK_PCT   = MARGIN_PCT  # back-compat alias for any code still importing this


def _secrets() -> dict:
    """Resolve OANDA credentials for this instance.

    Delegates to config.credentials.resolve_oanda_creds(), whose precedence is
    env vars > ~/.openclaw/secrets.env > config/credentials.local.json[mode]
    (see that module).  This lets a fresh public-repo clone supply its own keys
    via the dashboard CONNECTION tab while leaving Brock's production box — which
    reads secrets.env — completely unaffected.  Falls back to the legacy
    secrets.env-only reader if the credentials module is unavailable."""
    try:
        from config.credentials import resolve_oanda_creds
        return resolve_oanda_creds()
    except Exception as exc:                          # never let creds import break init
        log.warning("credentials module unavailable (%s); using secrets.env only", exc)
        path = os.path.expanduser("~/.openclaw/secrets.env")
        out: dict = {}
        if os.path.exists(path):
            for raw in open(path):
                line = raw.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.replace("export ", "").strip()
                    out[k] = v.strip()
        return out


class OandaBroker:
    """Thin wrapper over OANDA REST v3 — keeps no state beyond credentials."""

    def __init__(self):
        s = _secrets()
        self._base  = s.get("OANDA_API_URL",   "").rstrip("/")
        self._token = s.get("OANDA_API_TOKEN",  "")
        self._acct  = s.get("OANDA_ACCOUNT_ID", "")

    # ── Raw HTTP ─────────────────────────────────────────────────────────────

    def _req(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req  = urllib.request.Request(
            self._base + path,
            method=method,
            headers={"Authorization": f"Bearer {self._token}",
                     "Content-Type": "application/json"},
            data=data,
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    # ── Account ──────────────────────────────────────────────────────────────

    def account_balance(self) -> float:
        """Cash balance (excludes uPL) — used for margin-pct sizing per V1 model."""
        try:
            s = self.account_summary()
            return float(s.get("balance", 0.0))
        except Exception:
            return 0.0

    def account_nav(self) -> float:
        """Current account NAV in account currency (USD)."""
        summary = self._req("GET", f"/v3/accounts/{self._acct}/summary")
        return float(summary["account"]["NAV"])

    def account_summary(self) -> dict:
        """Full account metrics for the dashboard."""
        s = self._req("GET", f"/v3/accounts/{self._acct}/summary")["account"]
        return {
            "nav":           round(float(s.get("NAV", 0)), 2),
            "balance":       round(float(s.get("balance", 0)), 2),
            "unrealized_pl": round(float(s.get("unrealizedPL", 0)), 2),
            "margin_used":   round(float(s.get("marginUsed", 0)), 2),
            "open_trades":   int(s.get("openTradeCount", 0)),
            "pl":            round(float(s.get("pl", 0)), 2),
        }

    def _margin_rate(self, pair: str) -> float:
        """OANDA per-instrument margin rate (e.g. 0.02 = 50:1). Cached on broker."""
        if not hasattr(self, "_margin_rates_cache"):
            try:
                r = self._req("GET", f"/v3/accounts/{self._acct}/instruments")
                self._margin_rates_cache = {
                    i["name"]: float(i["marginRate"])
                    for i in r.get("instruments", [])
                }
                log.info("loaded margin rates for %d instruments", len(self._margin_rates_cache))
            except Exception as exc:
                log.warning("failed to load margin rates: %s -- using 5%% fallback", exc)
                self._margin_rates_cache = {}
        return self._margin_rates_cache.get(pair, 0.05)

    def _pair_mid(self, pair: str) -> float:
        try:
            r = self._req("GET",
                f"/v3/accounts/{self._acct}/pricing?instruments={pair}")
            p = r["prices"][0]
            return (float(p["bids"][0]["price"]) + float(p["asks"][0]["price"])) / 2.0
        except Exception as exc:
            log.warning("pricing failed for %s: %s", pair, exc)
            return 0.0

    def _base_price_usd(self, pair: str) -> float:
        """Spot price of 1 base-currency unit in USD (account currency).
           USD-base: 1.0. USD-quote: spot(pair). Cross: spot(base_USD)."""
        base, quote = pair[:3], pair[-3:]
        if base == "USD":
            return 1.0
        if quote == "USD":
            return self._pair_mid(pair) or 1.0
        conv = f"{base}_USD"
        return self._pair_mid(conv) or 1.0

    def open_positions(self) -> list[dict]:
        """List of currently open trades."""
        return self._req("GET", f"/v3/accounts/{self._acct}/openTrades").get("trades", [])

    # ── Position sizing ──────────────────────────────────────────────────────

    def size_units(
        self,
        pair:        str,
        direction:   str,
        margin_pct:  float | None = None,
        sl_pips:     float | None = None,  # accepted but ignored (legacy kw)
        risk_pct:    float | None = None,  # legacy alias: treated as margin_pct
    ) -> int:
        """Margin-based sizing (V1 model).

        units = (balance * margin_pct) / (base_price_usd * margin_rate)

        SL distance is NOT in this formula -- the SL is set independently by the
        ratchet config. Old keyword args (sl_pips, risk_pct) are accepted so the
        engine call site keeps working during the transition; if margin_pct is
        None we fall back to risk_pct, then MARGIN_PCT.
        """
        if margin_pct is None:
            margin_pct = risk_pct if risk_pct is not None else MARGIN_PCT
        bal = self.account_balance()
        if bal <= 0:
            log.warning("size_units %s: balance %.2f <= 0; 1k fallback", pair, bal)
            return 1000
        target_margin = bal * float(margin_pct)
        base_px_usd   = self._base_price_usd(pair)
        rate          = self._margin_rate(pair)
        if base_px_usd <= 0 or rate <= 0:
            log.warning("size_units %s: bad base_px=%.5f rate=%.4f; 1k fallback",
                        pair, base_px_usd, rate)
            return 1000
        units = int(target_margin / (base_px_usd * rate))
        log.debug("size_units %s | bal=%.2f mp=%.4f target=$%.2f base_usd=%.5f rate=%.4f -> %d units",
                  pair, bal, margin_pct, target_margin, base_px_usd, rate, units)
        return max(1, units)

    # ── Trade execution ──────────────────────────────────────────────────────

    def place_market(
        self,
        pair:      str,
        direction: str,    # "long" | "short"
        units:     int,
        sl_pips:   float = DEFAULT_INITIAL_SL_PIPS,
        entry_price: Optional[float] = None,
        client_ext: Optional[dict] = None,
        tp_pips:   float = 0.0,
    ) -> dict:
        """Place a market order with an initial server-side stop loss.

        sl_pips: pips from entry for the hard SL. This is the backstop before
                 the ratchet engages at 60min. Default = 20p.
        Returns the OANDA trade object (has 'id' key for later reference).
        """
        pip     = PIP[pair]
        signed  = units if direction == "long" else -units

        # Fetch live mid to compute SL price if not provided
        if entry_price is None:
            try:
                px = self._req(
                    "GET",
                    f"/v3/accounts/{self._acct}/pricing?instruments={pair}"
                )["prices"][0]
                bid = float(px["bids"][0]["price"])
                ask = float(px["asks"][0]["price"])
                entry_price = ask if direction == "long" else bid
            except Exception as exc:
                raise RuntimeError(f"Cannot fetch pricing for SL calc: {exc}") from exc

        sl_price = (entry_price - sl_pips * pip if direction == "long"
                    else entry_price + sl_pips * pip)   # estimate, for the log line only

        # OANDA price precision: JPY pairs 3dp, others 5dp
        prec = 3 if "JPY" in pair else 5

        order: dict = {
            "type":       "MARKET",
            "instrument": pair,
            "units":      str(signed),
            # D-5 (2026-07-28, external review): SL as a DISTANCE — OANDA
            # anchors it to the ACTUAL fill. The old absolute price was
            # computed from the pre-order quote, so entry slippage silently
            # widened or narrowed the real stop distance.
            "stopLossOnFill": {"distance": f"{sl_pips * pip:.{prec}f}"},
        }
        # Exit-gear persistence: survives restarts so recovery re-adopts the
        # trade's ENTRY gear instead of exit_config defaults (AUDIT_TODO item).
        if client_ext:
            order["tradeClientExtensions"] = client_ext
        # FAST slice class: server-side limit TP — fills at price or better,
        # cannot slip (stop-lock exits measured med 0.0 / p90 0.8p slippage).
        # NOTE (D-5): takeProfitOnFill has no distance form, so the TP remains
        # quote-anchored and inherits entry slippage. Bracket mode is currently
        # unused by the live book; revisit if it ever returns.
        if tp_pips and tp_pips > 0:
            tp_price = (entry_price + tp_pips * pip if direction == "long"
                        else entry_price - tp_pips * pip)
            order["takeProfitOnFill"] = {"price": f"{tp_price:.{prec}f}"}

        # D-5 stage D (external review): durable order INTENT id. If the POST
        # times out AFTER OANDA accepted the order, the fill would otherwise
        # become an unmanaged orphan (and a retry a duplicate). The id lets us
        # reconcile against the broker instead of guessing.
        intent_id = f"sv6-{int(time.time() * 1000)}-{os.urandom(3).hex()}"
        order["clientExtensions"] = {"id": intent_id, "tag": "sv6-order"}

        try:
            result = self._req("POST", f"/v3/accounts/{self._acct}/orders", {"order": order})
        except (socket.timeout, TimeoutError, urllib.error.URLError,
                ConnectionError) as exc:
            log.warning("place_market %s: transport error after send (%s) — "
                        "reconciling intent %s against the broker", pair, exc, intent_id)
            result = self._reconcile_order(intent_id)
            if result is None:
                raise RuntimeError(
                    f"order intent {intent_id} not found at broker after "
                    f"transport error ({exc}) — safe to treat as not placed") from exc
            log.info("place_market %s: RECONCILED intent %s — order had filled "
                     "despite the transport error (orphan averted)", pair, intent_id)
        trade  = result.get("orderFillTransaction", {})
        log.info("PLACED %s %s %d units | SL %.{prec}fp | trade_id=%s".replace("{prec}", str(prec)),
                 pair, direction, units, sl_price, trade.get("tradeOpened", {}).get("tradeID", "?"))
        return {"id": trade.get("tradeOpened", {}).get("tradeID", ""),
                "price": trade.get("price", ""),
                "raw": result}

    def _reconcile_order(self, intent_id: str) -> Optional[dict]:
        """Did an order we lost contact with actually execute? Look the order
        up BY CLIENT ID (OANDA: /orders/@{clientID}) and, if it filled, fetch
        the filling transaction so callers get the same shape a clean POST
        returns. None = the broker never saw it (safe to treat as not placed).
        """
        time.sleep(2.0)   # give the broker a beat to settle the order state
        try:
            r = self._req("GET", f"/v3/accounts/{self._acct}/orders/@{intent_id}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        order = r.get("order", {})
        state = order.get("state")
        if state != "FILLED":
            log.warning("reconcile %s: order state=%s — treating as not placed",
                        intent_id, state)
            return None
        fill_id = order.get("fillingTransactionID")
        if not fill_id:
            return None
        tx = self._req("GET",
                       f"/v3/accounts/{self._acct}/transactions/{fill_id}"
                       ).get("transaction", {})
        return {"orderFillTransaction": tx}

    def close_position(self, trade_id: str, units = "ALL") -> dict:
        """Close a trade by OANDA trade ID. units="ALL" = full close;
        positive int = partial close that many units (OANDA strips them from the
        position; remaining units stay open at the same entry, same SL)."""
        body_units = "ALL" if (units == "ALL" or units is None) else str(int(units))
        result = self._req(
            "PUT",
            f"/v3/accounts/{self._acct}/trades/{trade_id}/close",
            {"units": body_units},
        )
        log.info("CLOSED trade %s (units=%s)", trade_id, body_units)
        return result

    def move_stop(self, trade_id: str, new_sl_price: float, pair: str) -> dict:
        """Update the server-side stop loss for a trade (ratchet trail updates)."""
        prec = 3 if "JPY" in pair else 5
        return self._req(
            "PUT",
            f"/v3/accounts/{self._acct}/trades/{trade_id}/orders",
            {"stopLoss": {"price": f"{new_sl_price:.{prec}f}"}},
        )
