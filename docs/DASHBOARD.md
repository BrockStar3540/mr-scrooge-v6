# Mr. Scrooge V6 — Control Panel

The dashboard is a self-contained control panel served by `ops/server.py` on
`127.0.0.1:8084` (set `DASHBOARD_PORT` to change the port, `DASHBOARD_HOST`
to change the bind address — e.g. `0.0.0.0` or the machine's LAN IP to reach
the panel from another device on your network). SECURITY: the panel is
unauthenticated and has write endpoints (setup status, credentials,
practice/live mode, trading pause) — only bind beyond 127.0.0.1 on a network
where every host is trusted, never on an internet-facing interface. `ops/panel.html` is read
**fresh on every request**, so HTML/CSS/JS edits are live with no restart; only
`ops/server.py` changes need a process restart.

## The two top banners

A strip across the very top is always visible, with two halves:

- **Left — mode banner:** fat **PRACTICE (green)** / **LIVE (red)**, driven by
  `GET /api/credentials`. Tells you at a glance whether the bot is pointed at
  paper or real money. Change it in the **CONNECTION** tab (LIVE is heavily
  gated — see below).
- **Right — TRADING switch:** **TRADING: ON (green)** / **PAUSED (amber)**, a
  clickable master switch driven by `GET /api/state` → `trading_enabled`.
  **Pause ≠ kill.** Pausing suppresses *new entries* only; open positions keep
  being managed (ratchet trailing + server-side stops keep running). It does
  **not** stop the process — to fully stop, `systemctl --user stop mr-scrooge-v6`.
  See the TRADING control below for the friction involved.

## Running it (fresh clone)

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
# Option A: enter your OANDA keys in the CONNECTION tab (writes config/credentials.local.json)
# Option B: cp config/credentials.example.json config/credentials.local.json  and edit
python main.py          # dry run (no orders); add --live to place orders
```

Paths are derived from the repo root — no hardcoded machine paths. With an empty
journal / no OANDA account the panel degrades gracefully (empty feeds, no crash).

## Tabs

Tabs appear in this order in the nav bar:

| Tab | What it shows / does |
|-----|----------------------|
| **LIVE** | Today's P/L hero, equity curve, the cell scoreboard mosaic, open positions (with live ratchet state), today's broker-verified trades, and the recent-events feed. Read-only. |
| **PAIRS** | Per-pair card: each session's cell rollup (ACTIVE/SHADOW/NO-SIDE/DISABLED) + live condition-proximity bars + indicator chips. Read-only. |
| **BOOK** | The full cell book (pair × session). Click a cell for full setup detail — including the **ACTIVE / SHADOW / DISABLED status control**. |
| **SHADOW** | The Shadowboard (cumulative stamp-forward scoreboard), the Setup Scoreboard (simulated EV vs expected), and the live CELLSHADOW stamp feed. **Each setup row carries the same status control** so you can promote a good shadow → ACTIVE or disable it here. |
| **TUNE** | **Live per-cell exit editor** + recovery-fallback defaults. |
| **RISK** | Portfolio risk caps (was "PLAYMAKER"; the retired cert gates are gone). |
| **INDICATORS** | Per-pair raw `MarketView` gauges + sparklines. Read-only. |
| **HEALTH** | Engine status, cycle timing, last trade fired. Read-only. |
| **SYSTEM** | CPU/RAM/disk gauges, service status, recent journal. Read-only. |
| **CONNECTION** | OANDA credentials (with editable API URLs) + the practice/live mode toggle. |

### The LIVE track-record card
The top of the **LIVE** tab (and the README badge) shows the **current
configuration's** live track record — equity + trades auto-updated hourly from
**broker-verified fills** (`livelog/`), not from the bot's own logs. It is scoped
to the *current* config only (Scrooge changes often; blending eras is noise), so
it is a small, honest sample — not a long-run promise. Prior configs and the
research "tuition" are a separate story ([docs/SCROOGE_HISTORY.md](SCROOGE_HISTORY.md)).

## Write controls

All writers **validate input, merge (never replace), write atomically**, and
touch only config on disk — never the open positions.

### Setup status — BOOK **and** SHADOW (`POST /api/cell/status`)
Each setup has a 3-way `ACTIVE / SHADOW / DISABLED` control writing its `status`
in `config/cells/<PAIR>.json`. It appears in the **BOOK** cell detail *and* on
every setup row of the **SHADOW** tab (Shadowboard + Setup Scoreboard), so you
can promote a good shadow → ACTIVE or disable it right where shadows are reviewed.
- **ACTIVE** = trades live · **SHADOW** = evaluates + logs, never trades ·
  **DISABLED** = off.
- Switching **to ACTIVE** pops a confirm dialog ("this enables LIVE trading…").
- Hot-reloads: the engine re-reads the pair file on mtime change, so the change
  applies on the **next scan cycle** — no restart. Every status surface
  re-fetches after a save.

### TRADING pause (`POST /api/trading`) — the top-bar switch
The right half of the top bar is a soft **trading pause**. It writes
`trading_enabled` to `config/runtime.json`, which the engine reads **every
cycle** (hot-reload, no restart).
- **Pause blocks new entries only.** Management of open positions (ratchet +
  server-side stops) keeps running — the pause never touches an open trade. It is
  **not** a process kill; a full stop is `systemctl --user stop mr-scrooge-v6`.
- **Pausing is unconfirmed** (the safe direction). **Resuming while in LIVE mode**
  requires the same `TRADE REAL MONEY` confirmation as other live actions;
  resuming in practice just asks a normal confirm.
- Fail-safe: if `config/runtime.json` is missing or unreadable the engine
  defaults to **ENABLED** (it never silently halts a running bot on a read
  error) and logs the fallback.

### TUNE — per-cell exit geometry (`POST /api/cell/exit`)
Edits the setup's live `exit` block: `sl_pips` (5–200), `trigger_pips` (0–50),
`trail_pips` (0–30), `trail_mult` (0–3). Values shown come straight from
`/api/cells` (they match the live config exactly). Merge-preserving: `mode`,
`trail_min/max`, `_class`, `tp_pips`, `timeout_min` are kept. `trail_pips` must
stay `< trigger_pips` (else the first ratchet lock ≤ 0). Hot-reloads next cycle.

The **Recovery fallback defaults** card below edits `config/exit_config.json` —
used **only** when a position is recovered after a restart with no per-cell
exit params. Live trades never use it.

### RISK — portfolio caps (`POST /api/config/playmaker`)
`margin_pct_per_trade`, `max_concurrent_trades`, `max_per_currency_direction`.
The save sends only the `account` block; `defaults`, `per_pair`, and all
governance (`disabled_cells`, `inverted_*`, `per_cell_*`, `_note*`) are preserved
verbatim server-side. Hot-reloads (read each new entry / playmaker cycle).

### CONNECTION — credentials + mode
Credentials are stored in `config/credentials.local.json` (chmod 600, **gitignored,
never committed**). Shape:
`{"practice":{"api_token","account_id","api_url"},"live":{...},"mode":"practice"}`.
Each set's **API URL is editable** and defaults to the OANDA host for its type
(`practice`→api-fxpractice, `live`→api-fxtrade), named in `config/credentials.py`
as `OANDA_PRACTICE_URL` / `OANDA_LIVE_URL`. Each field has a **"reset to OANDA
default"** link; a set with no stored `api_url` falls back to that default.

- `POST /api/credentials` accepts optional `api_url` (validated as a well-formed
  `https://` URL) and verifies the token **read-only** against it (`GET
  {api_url}/v3/accounts` must 200, the account_id must be visible, and its prefix
  must match the type — `101-`=practice, `00x-`=live). A non-OANDA URL naturally
  fails this check — a deliberate guard. Tokens are never logged or echoed
  (masked to `…last4`); `api_url` is not secret and is shown.
- `GET /api/credentials` returns status only — configured booleans, masked
  last4, current mode, and whether live is armed. Never the values.
- `POST /api/mode` is the toggle.

**Credential resolution precedence** (the broker's `_secrets()`):
1. environment `OANDA_API_TOKEN` / `OANDA_API_URL` / `OANDA_ACCOUNT_ID`
2. `~/.openclaw/secrets.env` (legacy production path)
3. `config/credentials.local.json`, selecting the set by `mode` (using that set's
   `api_url`, else the OANDA default for the type)

### Broker compatibility (OANDA only)
The editable API URL exists so you can point at a different OANDA host (e.g. a
region or a mock), **not** at a different broker. This bot and dashboard were
built, tested, and run **only** against **OANDA's v20 REST API**. Another
broker's API is almost certainly incompatible — different endpoints, auth, and
order/position/pricing shapes — so pointing the URL elsewhere will fail token
verification and, even past that, will not work without real code changes. The
OANDA-specific integration lives in **`core/broker/oanda.py`** (orders, stops,
sizing, account summary) and **`core/feed/oanda.py`** (pricing/candles feed); a
porter would need to reimplement both against the target broker's API.

secrets.env is deliberately kept **above** the local json so a production box
that reads secrets.env can never be re-pointed by a stray local file. A fresh
clone has no secrets.env, so it transparently uses the local json.

### ⚠ Live-mode guardrails
Switching to LIVE (real money) requires **all** of:
1. env `SCROOGE_ALLOW_LIVE=1` on the instance — otherwise `POST /api/mode`
   with `mode:"live"` returns **403** and the UI shows the option locked.
2. live credentials present + re-verified.
3. the typed confirmation string `TRADE REAL MONEY` in the request body (the UI
   shows a red modal spelling out the real-money risk + the negative-EV research
   note, see `docs/RESEARCH_PROGRAM.md`).

Switching mode does **not** auto-restart or open trades. Because broker
credentials load at engine init, **a restart is required for a mode/credential
change to take effect** — the UI says so and does not pretend it is live
instantly. Defence in depth: even if the local file says `mode:"live"`, the
broker refuses to resolve live creds unless `SCROOGE_ALLOW_LIVE=1`.
