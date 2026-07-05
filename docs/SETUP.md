# Mr. Scrooge V5 — Setup Manual

Complete guide to installing, configuring, and running V5 from scratch on a new machine.

---

## ⚠️  The Machine Must Stay On — Always

**This is the single most important operational requirement.**

V5 holds open OANDA positions that are actively managed every 20 minutes by the ratchet engine.
If the host machine sleeps, shuts down, or loses network connectivity:

- **Stop-losses stop moving.** The ratchet engine cannot advance the SL on a profitable trade.
- **No exits.** A trade moving against you won't be closed — OANDA's server-side SL is the only protection.
- **Recovery happens on restart**, but the SL resets to the OANDA server value (it never retreats), so no protection is lost — but profit locking stops until the engine is back.

**Recommended host**: A cloud VM (AWS EC2, etc.) configured to never auto-stop. EC2 in particular has no auto-sleep and the instance can be stopped only explicitly.

**Local machine**: If you must run locally, disable sleep in OS settings. macOS: System Settings → Battery → "Prevent automatic sleeping". Ubuntu: `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`. Even then, you are one power cut or lid-close away from an unmanaged position.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.12 tested in production |
| pip | any | bundled with Python |
| git | any | to clone and update |
| Network | stable | OANDA REST requires internet |
| OS | Linux (Ubuntu 22.04+) or macOS | Windows untested |

The bot runs comfortably on 1 vCPU, 1 GB RAM (t3.micro on EC2 works, but t3.small is recommended for headroom).

---

## 1. Clone the Repo

```bash
git clone https://github.com/BrockStar3540/mr-scrooge-v5.git
cd mr-scrooge-v5
```

> Private repo — you will need to authenticate with GitHub (token or SSH key).
> Generate a fine-grained Personal Access Token at https://github.com/settings/tokens with read access to `mr-scrooge-v5`.

---

## 2. Create a Virtual Environment

```bash
python3 -m venv mr_burns_env
source mr_burns_env/bin/activate
```

The venv can be named anything, but `mr_burns_env` matches the production systemd unit.
**Do not commit the venv to git** — it is already in `.gitignore`.

---

## 3. Install Python Packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Packages installed:

| Package | Version | Purpose |
|---|---|---|
| `oandapyV20` | ≥0.6.3 | OANDA REST v3 client (candles, pricing, orders) |
| `pandas` | ≥2.0 | Candle processing and indicator computation |
| `numpy` | ≥1.25 | Numerical operations (ATR, RSI, Z-score) |
| `requests` | ≥2.31 | HTTP calls to OANDA REST directly where oandapyV20 is bypassed |

No ML framework is required for V5 (unlike V4's brain). All signal logic is deterministic weighted scoring.

---

## 4. OANDA Account Setup

### 4a. Create an Account

- **Practice (paper trading)**: https://fxtrade.oanda.com/account/login  (free, no real money)
- **Live**: https://www.oanda.com/us-en/trading/ (requires identity verification)

### 4b. Get Your API Token

1. Log in to your OANDA account
2. Navigate to **My Account** → **Manage API Access** (or https://www.oanda.com/us-en/trading/api-keys/)
3. Click **Generate** to create a new token
4. Copy the token immediately — OANDA only shows it once

### 4c. Find Your Account ID

Your account ID appears in the OANDA platform. Format: `001-001-XXXXXXX-001`

You can also retrieve it via API once you have the token:
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://api-fxtrade.oanda.com/v3/accounts
```
(Use `api-fxpractice.oanda.com` for practice accounts.)

### 4d. Base URLs

| Account type | OANDA_API_URL |
|---|---|
| Practice | `https://api-fxpractice.oanda.com` |
| Live | `https://api-fxtrade.oanda.com` |

---

## 5. Create the Secrets File

V5 reads credentials from `~/.openclaw/secrets.env`. This file is **never committed to git**.

```bash
mkdir -p ~/.openclaw
cat > ~/.openclaw/secrets.env << 'EOF'
OANDA_API_URL=https://api-fxtrade.oanda.com
OANDA_API_TOKEN=your_token_here
OANDA_ACCOUNT_ID=001-001-XXXXXXX-001
GITHUB_TOKEN_SCROOGE_V5=your_github_token_here
EOF
chmod 600 ~/.openclaw/secrets.env
```

The file is sourced at process start — never pass credentials as command-line arguments or set them as plain environment variables in systemd units.

### Verify credentials

```bash
source mr_burns_env/bin/activate
python3 -c "
import os, json, urllib.request
secrets = dict(l.strip().split('=',1) for l in open(os.path.expanduser('~/.openclaw/secrets.env')) if '=' in l and not l.startswith('#'))
token = secrets['OANDA_API_TOKEN']
url   = secrets['OANDA_API_URL'] + '/v3/accounts'
req   = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
resp  = json.loads(urllib.request.urlopen(req).read())
print('Accounts found:', [a['id'] for a in resp['accounts']])
"
```

---

## 6. Test in Dry-Run Mode

Before any live trading, run the bot in dry-run mode. It will fetch live OANDA market data and compute signals — but will **not place any orders**.

```bash
cd mr-scrooge-v5
source mr_burns_env/bin/activate
python main.py
```

Expected output:
```
INFO v5.main  DRY RUN mode — pass --live to enable order execution
INFO v5.engine  V5 engine ready | dry_run=True | 8 pairs | 24 dir_mods | 24 mom_mods
INFO v5.dashboard  Dashboard started on port 8084 — https://...
INFO v5.engine  V5 engine starting (dry_run=True, interval=300s)
```

The dashboard will be available at `http://localhost:8084/` in dry-run mode. Every 5 minutes you will see signal summaries in the logs.

---

## 7. Run Live

```bash
python main.py --live
```

The `--live` flag enables order execution. The engine will:
1. Read live OANDA candles every 5 minutes
2. Score direction + momentum for all 8 pairs
3. Place a market order if the best candidate clears all gate floors
4. Set a server-side stop-loss at −15 pips on fill
5. Run the ratchet every 20 minutes to advance the SL on profitable trades

> **Start during a low-volatility session** (Asia or early London) for the first live run so you can observe the first few signal cycles before a trade fires.

---

## 8. Setting Up as a System Service (Recommended)

Running via systemd ensures the bot restarts automatically after a crash or OS reboot. This is the production setup.

### 8a. Copy the service file

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/mr-scrooge-v5.service << 'EOF'
[Unit]
Description=Mr. Scrooge V5 Trading Platform (LIVE)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/mr-scrooge-v5
ExecStart=/home/ubuntu/mr_burns_env/bin/python3 main.py --live
Restart=always
RestartSec=15
Environment=PYTHONUNBUFFERED=1
TimeoutStopSec=30
KillSignal=SIGTERM
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF
```

> Adjust `WorkingDirectory` and `ExecStart` paths if your install is not at `/home/ubuntu/mr-scrooge-v5`.

### 8b. Enable and start

```bash
systemctl --user daemon-reload
systemctl --user enable mr-scrooge-v5    # start on boot
systemctl --user start mr-scrooge-v5     # start now
systemctl --user status mr-scrooge-v5    # confirm running
```

### 8c. Enable lingering (EC2 / Linux — required for user services to survive logout)

```bash
loginctl enable-linger $USER
```

Without this, `--user` services stop when you log out of SSH.

---

## 9. EC2 Setup (Production)

EC2 is the recommended always-on host. The production instance uses `t3.small` on `ap-southeast-2` (or similar).

### Key EC2 considerations

| Item | Detail |
|---|---|
| Instance type | `t3.small` (2 vCPU, 2 GB RAM) — minimum `t3.micro` (1 GB) |
| Storage | 20 GB gp3 — logs and candle data grow slowly |
| Auto-stop | Disable EC2 auto-stop / auto-hibernate in instance settings |
| Security group | Inbound: SSH (22) + Tailscale (UDP 41641). No public HTTP needed. |
| Reboot | Set EC2 console → **Actions → Instance Settings → Change shutdown behavior → Stop** (not terminate) |
| RAM warning | **Do not run heavy ML jobs on the same instance as the live bot.** A memory-exhausted process can freeze the trader. Use a separate machine for compute (e.g. Mac Mini). |

### EC2 quick-start after a fresh Ubuntu 22.04 AMI

```bash
# 1. Update and install Python 3.12
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip git

# 2. Clone repo
git clone https://github.com/BrockStar3540/mr-scrooge-v5.git
cd mr-scrooge-v5

# 3. Venv + install
python3.12 -m venv ~/mr_burns_env
source ~/mr_burns_env/bin/activate
pip install --upgrade pip && pip install -r requirements.txt

# 4. Secrets
mkdir -p ~/.openclaw
nano ~/.openclaw/secrets.env      # fill in OANDA_API_URL, OANDA_API_TOKEN, OANDA_ACCOUNT_ID
chmod 600 ~/.openclaw/secrets.env

# 5. Service
mkdir -p ~/.config/systemd/user
cp ops/mr-scrooge-v5.service ~/.config/systemd/user/  # (or create manually — see Section 8)
systemctl --user daemon-reload
loginctl enable-linger $USER
systemctl --user enable --now mr-scrooge-v5
```

---

## 10. Dashboard

The bot serves a 4-tab control panel at **port 8084**. It updates every 10 seconds.

| Tab | What you see |
|---|---|
| **LIVE** | Account NAV / balance / P&L / margin, open positions with ratchet state (entry, age, SL locked, peak MFE, net pips, unrealised P&L), event feed |
| **PAIRS** | Per-pair signal cards: direction bias, score, certainty %, vol regime, expected pips, indicator chips |
| **HEALTH** | Engine status table, per-pair feed health, last-cycle timestamp |
| **SYSTEM** | CPU / RAM / disk gauges, service status table, live journal log |

### Local access

```
http://localhost:8084/
```

### Remote access via Tailscale (production setup)

Install [Tailscale](https://tailscale.com) on the EC2 host and your local machine. Then configure Tailscale Serve to expose the dashboard as HTTPS on the Tailscale network:

```bash
# On the EC2 host — one-time setup
sudo tailscale serve --bg --https=8084 http://127.0.0.1:8084
```

After that, the dashboard is accessible from any device on your Tailscale network at:
```
https://<your-ec2-tailscale-hostname>:8084/
```

No public internet exposure, no open ports, HTTPS certificate managed by Tailscale automatically.

---

## 11. Ratchet Exit — Live-Editable Config

The ratchet settings live in `config/exit_config.json`. You can edit this file while the bot is running — changes take effect on the **next 20-minute ratchet cadence**, no restart needed.

```json
{
  "step_engage_min":   0.0,
  "step_cadence_min":  20.0,
  "step_size_pips":    5.0,
  "step_trigger_pips": 10.0,
  "step_trail_pips":   6.0
}
```

| Key | Description | Production value |
|---|---|---|
| `step_engage_min` | Minutes after fill before ratchet activates | `0.0` (immediate) |
| `step_cadence_min` | How often (minutes) to check and possibly advance SL | `20.0` |
| `step_trigger_pips` | Peak MFE must exceed this before first lock | `10.0` |
| `step_size_pips` | Gap between lock levels | `5.0` |
| `step_trail_pips` | SL parks this many pips below the current level | `6.0` |

**Lock ladder** (with production defaults):

| Peak MFE | SL moves to |
|---|---|
| +10p | +4p |
| +15p | +9p |
| +20p | +14p |
| +25p | +19p |
| +30p | +24p |
| … | … (uncapped) |

Initial SL: **−15p** from entry (placed server-side by OANDA at order fill). The ratchet only moves SL forward — never back.

---

## 12. Monitoring and Logs

```bash
# Follow live logs
journalctl --user -u mr-scrooge-v5 -f -o cat

# Last 100 lines
journalctl --user -u mr-scrooge-v5 -n 100 --no-pager

# Service status
systemctl --user status mr-scrooge-v5

# Restart
systemctl --user restart mr-scrooge-v5

# Stop (positions remain open on OANDA, ratchet pauses)
systemctl --user stop mr-scrooge-v5
```

**What RECOVERED means in logs**: on every restart, V5 reads OANDA's current open trades and reconstructs the ratchet state from the existing server-side stop-loss. `RECOVERED EUR_JPY short | entry=X | sl_locked=-15.0` means V5 has taken over management of that trade. The SL never retreats on restart.

---

## 13. Updating the Bot

```bash
# On EC2
cd mr-scrooge-v5
git pull origin main
systemctl --user restart mr-scrooge-v5
```

The ratchet config can be updated without restarting (just edit `config/exit_config.json`). Code changes require a restart.

---

## 14. Trading Pairs and Sessions

V5 trades 8 pairs, each only during its active session(s):

| Pair | Active Sessions | Pip value |
|---|---|---|
| AUD_JPY | Asia, London | 0.01 |
| AUD_USD | Asia, London, NY | 0.0001 |
| EUR_JPY | London, NY | 0.01 |
| EUR_USD | London, NY | 0.0001 |
| GBP_USD | London, NY | 0.0001 |
| USD_CAD | NY | 0.0001 |
| USD_CHF | London, NY | 0.0001 |
| USD_JPY | Asia, London, NY | 0.01 |

Session windows (UTC):

| Session | UTC hours |
|---|---|
| Asia | 22:00 – 07:00 |
| London | 09:00 – 15:00 |
| NY | 13:00 – 22:00 |

---

## 15. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `OANDA_API_TOKEN is empty` at startup | Secrets file not found or wrong path | Check `~/.openclaw/secrets.env` exists and is `chmod 600` |
| Bot starts but places no trades for hours | Low-certainty session, spread gates firing, or off-hours | Check the PAIRS tab on the dashboard for actionable=false details |
| `RECOVERED` on every restart but ratchet not advancing | Bot restarting too frequently | Check logs for crash loop; increase `RestartSec` in the service unit |
| Dashboard shows stale data | Engine cycle stalled | Check logs for error; restart the service |
| `ConnectionError` from OANDA | Network interruption or rate limit | Bot auto-retries; if persistent check the OANDA status page |
| High RAM usage | Too many open candle requests | Ensure no other heavy processes on the same machine |

---

## Quick Reference

```bash
# Start / stop / restart
systemctl --user start|stop|restart mr-scrooge-v5

# Logs
journalctl --user -u mr-scrooge-v5 -f -o cat

# Dry run (no orders)
source mr_burns_env/bin/activate && python main.py

# Dashboard
http://localhost:8084/

# Edit ratchet live (no restart needed)
nano config/exit_config.json

# Run tests
source mr_burns_env/bin/activate && python -m pytest tests/ -v
```
