# Mr. Scrooge V6 — Setup

A from-zero guide to installing, configuring, and running V6 on a fresh machine.
It starts in **practice** (paper) mode; going live with real money is deliberate
and gated (see §5). If you just want to read the dashboard, see
[docs/DASHBOARD.md](DASHBOARD.md).

> **Honesty up front:** this bot's own research shows **no price-prediction edge
> net of cost** on retail OANDA majors — it is run as a live falsification
> experiment on a practice account, not a money-maker. Read
> [docs/RESEARCH_PROGRAM.md](RESEARCH_PROGRAM.md) before pointing it at real funds.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ (3.12 tested) | `python3 --version` |
| pip + venv | bundled | `python3 -m venv --help` |
| git | any | to clone + update |
| Network | stable | OANDA REST needs internet |
| OS | Linux (Ubuntu 22.04+) or macOS | Windows untested |

Runs comfortably on 1 vCPU / 1 GB RAM.

**An OANDA account** (the broker this bot integrates with — the *only* broker it
supports, see [Broker compatibility](DASHBOARD.md#broker-compatibility-oanda-only)):
- **Practice** is free, no real money, no identity check — create one at
  <https://www.oanda.com/> (fxTrade Practice). Use this.
- Live requires identity verification. Don't, until you've read the research.

### Get a v20 API token + account id
1. Log in to OANDA → **Manage API Access** (<https://www.oanda.com/> account
   settings) → **Generate** a personal access token. Copy it — it's shown once.
2. Your **account id** looks like `101-001-1234567-001`. Practice ids start
   `101-`; live ids start `00x-` (e.g. `001-`). You can also list them:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
        https://api-fxpractice.oanda.com/v3/accounts
   ```

---

## 2. Clone + virtual environment

```bash
git clone https://github.com/BrockStar3540/mr-scrooge-v6.git
cd mr-scrooge-v6
python3 -m venv mr_burns_env         # any name; this one matches the service unit
source mr_burns_env/bin/activate
```

All paths below are relative to the repo root — nothing is hardcoded to a
particular machine.

---

## 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt`: `oandapyV20`, `pandas`, `numpy`, `requests`. No ML framework
is needed at runtime — entry logic is per-cell validated indicator conditions
from `config/cells/`; the ML lives offline in the research pipeline only.

---

## 4. Configure credentials

You need to tell the bot your OANDA token + account id. **Two ways** — the
dashboard is easiest.

### Option A — the dashboard CONNECTION tab (recommended)
1. Start the bot in dry-run (no orders — safe): `python main.py`
2. Open the dashboard: <http://localhost:8084/>
3. Go to the **CONNECTION** tab → **PRACTICE** card → paste your practice token +
   account id → **Verify + save practice**. The dashboard verifies the token
   read-only against OANDA and writes `config/credentials.local.json`
   (chmod 600, gitignored — never committed). Restart the bot to pick them up.

### Option B — a file or environment variables
- **File:** `cp config/credentials.example.json config/credentials.local.json`
  and fill in the `practice` block (`api_token`, `account_id`, optional `api_url`).
- **Env vars:** export `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, and
  `OANDA_API_URL` (`https://api-fxpractice.oanda.com` for practice).

**Resolution precedence** (highest first): environment `OANDA_*` vars →
`~/.openclaw/secrets.env` → `config/credentials.local.json`. So env vars always
win; the dashboard file is the fallback a fresh clone uses.

---

## 5. Practice vs live — the two switches that matter

There are **two independent** ideas; keep them straight:

| Switch | What it controls | Default |
|---|---|---|
| `python main.py` vs `--live` | whether orders are placed **at all** | no `--live` = **dry run**, zero orders |
| Trading **mode** (practice/live) | **which OANDA account** orders go to | **practice** (paper money) |

- `python main.py` → dry run. Fetches live data, computes + logs signals, serves
  the dashboard, but **never places an order**. Safe for observation.
- `python main.py --live` → actually places orders **on the configured account**.
  With practice credentials that's **paper money** — the normal way to run.
- **Real money** requires all of: (a) live credentials saved, (b) the instance
  armed with `SCROOGE_ALLOW_LIVE=1` in the environment, and (c) flipping mode to
  LIVE in the CONNECTION tab, which makes you type `TRADE REAL MONEY` to confirm.
  Absent (b), the bot refuses to resolve live credentials and stays on practice.
  Don't arm real money until you've read [the research](RESEARCH_PROGRAM.md).

---

## 6. Run it

```bash
source mr_burns_env/bin/activate
python main.py            # dry run (no orders) — good first run
python main.py --live     # place orders on the configured account (practice = paper)
```

Expected startup logs:
```
INFO v5.main       DRY RUN mode — pass --live to enable order execution
INFO v5.cells      cells: loaded config for AUD_JPY (3 sessions)   # one per pair
INFO v5.dashboard  Dashboard started on 127.0.0.1:8084
INFO v5.engine     V5 engine ready (cell_v1) | dry_run=True | 8 pairs
```

Dashboard: <http://localhost:8084/> (change the port with `DASHBOARD_PORT`).
The two banners at the top show your **mode** (PRACTICE/LIVE) and the **TRADING**
pause state. Stop with **Ctrl-C** (open positions stay open on OANDA under their
server-side stops).

---

## 7. Run as a service (always-on hosts)

For an always-on host, run it under systemd so it restarts after a crash/reboot.
The repo ships a user unit at `ops/mr-scrooge-v6.service` (it uses `%h`, so no
machine-specific paths):

```bash
mkdir -p ~/.config/systemd/user
cp ops/mr-scrooge-v6.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mr-scrooge-v6
loginctl enable-linger "$USER"     # keep --user services alive after logout (Linux)
```

The shipped unit runs `main.py --live` on port 8084. It does **not** set
`SCROOGE_ALLOW_LIVE`, so it stays on practice unless you deliberately arm it.

```bash
systemctl --user status  mr-scrooge-v6
systemctl --user restart mr-scrooge-v6          # after a code change
systemctl --user stop    mr-scrooge-v6          # full stop (positions stay open on OANDA)
journalctl --user -u mr-scrooge-v6 -f -o cat    # follow logs
```

> **Keep the host awake.** While the process is down, the ratchet can't advance
> stops — only OANDA's server-side stop protects an open trade. On a laptop,
> disable sleep. To pause *trading* without stopping management, use the
> dashboard **TRADING** switch (see [DASHBOARD.md](DASHBOARD.md)) — that keeps
> exits running.

---

## 8. Verify / operate

- **Tests:** `pip install -r requirements-dev.txt` once, then `python -m pytest tests/ -q`
- **Live-edit config without a restart:** per-cell exits (TUNE tab), risk caps
  (RISK tab), setup status (BOOK/SHADOW tabs), and the trading pause all
  hot-reload on the next cycle. Only credential/mode changes and code changes
  need a restart.
- **Update:** `git pull origin main && systemctl --user restart mr-scrooge-v6`

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard won't load at `:8084` | bot not running, or wrong port | check `python main.py` is up / `systemctl --user status mr-scrooge-v6`; port is `DASHBOARD_PORT` (default 8084); it binds `127.0.0.1` only |
| Credentials fail to verify | wrong token, wrong account id, or prefix/type mismatch | practice ids start `101-`, live `00x-`; the token must be able to see that account id on that host |
| Mode toggle to LIVE is locked / 403 | instance not armed | set `SCROOGE_ALLOW_LIVE=1` in the environment (only if you truly mean real money) |
| No trades appearing | market closed, dry-run, or trading paused | FX is closed weekends; check you passed `--live`; check the top-bar **TRADING** switch isn't PAUSED; the PAIRS/BOOK tabs show why a setup didn't fire |
| `RECOVERED …` on every restart | normal | on restart the engine re-adopts open trades from OANDA and their server-side stop; the SL never retreats |
| High RAM / stalls | heavy job on the same box | don't run heavy compute beside the live bot |

---

## Quick reference

```bash
source mr_burns_env/bin/activate
python main.py            # dry run (no orders)
python main.py --live     # place orders (practice account by default)
python -m pytest tests/ -q
# dashboard: http://localhost:8084/   (CONNECTION tab = credentials; top bar = mode + trading pause)
systemctl --user start|stop|restart mr-scrooge-v6
journalctl --user -u mr-scrooge-v6 -f -o cat
```
