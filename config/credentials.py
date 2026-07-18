"""config/credentials.py — per-user OANDA credential resolution.

Mr. Scrooge V6 ships as a PUBLIC repo, but every operator runs a PRIVATE
instance with their OWN OANDA keys.  This module owns:
  • where credentials come from (resolution precedence, below), and
  • the read / write / validate logic behind the dashboard CONNECTION tab.

Local storage
-------------
config/credentials.local.json  (chmod 0600, GITIGNORED — must NEVER be committed):

    {
      "practice": {"api_token": "...", "account_id": "101-...", "api_url": "https://..."},
      "live":     {"api_token": "...", "account_id": "001-...", "api_url": "https://..."},
      "mode":     "practice"
    }

Each set's api_url is editable (CONNECTION tab) and defaults to the OANDA host
for its type (OANDA_PRACTICE_URL / OANDA_LIVE_URL).  A set with no api_url falls
back to that default.  Env OANDA_API_URL still wins on the production box.

Resolution precedence — resolve_oanda_creds()  (highest first)
--------------------------------------------------------------
  1. Environment variables  OANDA_API_TOKEN / OANDA_API_URL / OANDA_ACCOUNT_ID.
  2. ~/.openclaw/secrets.env   (legacy production path).
  3. config/credentials.local.json,  selecting the practice|live set by "mode".

  ⚠ SAFETY: secrets.env is kept ABOVE credentials.local.json on purpose.  The
  live EC2 production box feeds its broker from secrets.env (verified: the v6
  systemd unit does NOT export OANDA_* into the process env), so ranking the
  file above the local json guarantees a stray credentials.local.json can never
  silently re-point the live box.  A fresh clone has no secrets.env, so it
  transparently falls through to the local json a downloader writes via the UI.

  ⚠ LIVE ARM GATE: even if credentials.local.json says mode="live", the broker
  refuses to resolve LIVE creds unless env SCROOGE_ALLOW_LIVE=1 is set — it
  falls back to the practice set (defence in depth beneath the /api/mode gate).
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("v6.credentials")

_REPO_ROOT = Path(__file__).resolve().parents[1]
CREDS_PATH = _REPO_ROOT / "config" / "credentials.local.json"

MODES = ("practice", "live")
# Named OANDA v20 REST hosts — the DEFAULT api_url for each account type. A
# credential set may override its own api_url (CONNECTION tab), but these remain
# the fallback + the "Reset to OANDA default" target.
OANDA_PRACTICE_URL = "https://api-fxpractice.oanda.com"
OANDA_LIVE_URL     = "https://api-fxtrade.oanda.com"
OANDA_HOSTS = {"practice": OANDA_PRACTICE_URL, "live": OANDA_LIVE_URL}
_SECRETS_ENV = os.path.expanduser("~/.openclaw/secrets.env")


# ── Small helpers ─────────────────────────────────────────────────────────────
def allow_live() -> bool:
    """True only when this instance is deliberately armed for real-money mode."""
    return os.environ.get("SCROOGE_ALLOW_LIVE", "") == "1"


def default_url_for(mode: str) -> str:
    """The OANDA default host for an account type."""
    return OANDA_LIVE_URL if mode == "live" else OANDA_PRACTICE_URL


def valid_https_url(url: str | None) -> bool:
    """A well-formed https:// URL with a host (no query/fragment required)."""
    if not url or not isinstance(url, str):
        return False
    try:
        p = urllib.parse.urlparse(url.strip())
    except Exception:
        return False
    return p.scheme == "https" and bool(p.netloc) and " " not in url.strip()


def url_for_set(cset: dict, mode: str) -> str:
    """The api_url a credential set should use — its own override, else the
    OANDA default for the type."""
    u = (cset or {}).get("api_url")
    return u.rstrip("/") if (u and valid_https_url(u)) else default_url_for(mode)


def mask(token: str | None) -> str:
    """Never echo a token — show only a '…last4' fingerprint."""
    if not token:
        return "—"
    t = str(token)
    return "…" + t[-4:] if len(t) >= 4 else "…"


def account_prefix_type(account_id: str | None) -> str | None:
    """OANDA account-id prefix → account type.

    Practice ids start '101-'; live ids start '00x-' (001-, 002-, …).
    Returns 'practice' | 'live' | None (unknown/garbage)."""
    if not account_id:
        return None
    a = str(account_id)
    if a.startswith("101-"):
        return "practice"
    if re.match(r"^00\d-", a):
        return "live"
    return None


# ── Local credential file I/O ─────────────────────────────────────────────────
def load_local() -> dict:
    """Parse credentials.local.json → dict (empty dict if absent/malformed)."""
    try:
        return json.loads(CREDS_PATH.read_text())
    except FileNotFoundError:
        return {}
    except Exception as exc:                       # malformed → treat as empty
        log.warning("credentials.local.json unreadable: %s", exc)
        return {}


def write_local(data: dict) -> None:
    """Atomically write credentials.local.json with chmod 0600."""
    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CREDS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(CREDS_PATH)
    try:
        os.chmod(CREDS_PATH, 0o600)
    except OSError:
        pass


def _secrets_env() -> dict:
    """Legacy ~/.openclaw/secrets.env reader (Brock's production path)."""
    out: dict = {}
    if os.path.exists(_SECRETS_ENV):
        for raw in open(_SECRETS_ENV):
            line = raw.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.replace("export ", "").strip()] = v.strip()
    return out


# ── Resolution (used by the broker) ───────────────────────────────────────────
def resolve_oanda_creds() -> dict:
    """Resolve the OANDA credential set the broker should use.

    Returns {"OANDA_API_URL", "OANDA_API_TOKEN", "OANDA_ACCOUNT_ID", "_source"}.
    See module docstring for precedence + the live-arm safety gate."""
    env_tok = os.environ.get("OANDA_API_TOKEN")
    if env_tok:
        return {
            "OANDA_API_URL":    os.environ.get("OANDA_API_URL", OANDA_HOSTS["practice"]).rstrip("/"),
            "OANDA_API_TOKEN":  env_tok,
            "OANDA_ACCOUNT_ID": os.environ.get("OANDA_ACCOUNT_ID", ""),
            "_source":          "env",
        }

    s = _secrets_env()
    if s.get("OANDA_API_TOKEN"):
        return {
            "OANDA_API_URL":    s.get("OANDA_API_URL", OANDA_HOSTS["practice"]).rstrip("/"),
            "OANDA_API_TOKEN":  s.get("OANDA_API_TOKEN", ""),
            "OANDA_ACCOUNT_ID": s.get("OANDA_ACCOUNT_ID", ""),
            "_source":          "secrets_env",
        }

    local = load_local()
    mode = local.get("mode", "practice")
    if mode not in MODES:
        mode = "practice"
    # LIVE arm gate — never resolve live creds unless the box is armed.
    if mode == "live" and not allow_live():
        log.warning("credentials.local.json mode=live but SCROOGE_ALLOW_LIVE unset "
                    "— falling back to practice creds (live disabled on this instance)")
        mode = "practice"
    cset = local.get(mode) or {}
    return {
        "OANDA_API_URL":    url_for_set(cset, mode),   # per-set override, else OANDA default
        "OANDA_API_TOKEN":  cset.get("api_token", ""),
        "OANDA_ACCOUNT_ID": cset.get("account_id", ""),
        "_source":          f"local:{mode}",
    }


# ── Token verification (used by POST /api/credentials + POST /api/mode) ────────
def _fetch_account_ids(host: str, api_token: str) -> list[str]:
    """READ-ONLY GET {host}/v3/accounts → list of account ids visible to the
    token.  Raises urllib.error.HTTPError on a non-2xx (e.g. bad token → 401).

    Broken out as its own function so tests monkeypatch it instead of the net."""
    req = urllib.request.Request(
        host.rstrip("/") + "/v3/accounts",
        headers={"Authorization": f"Bearer {api_token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return [a.get("id") for a in data.get("accounts", []) if a.get("id")]


def verify_oanda_token(mode: str, api_token: str, account_id: str,
                       api_url: str | None = None) -> tuple[bool, str]:
    """Validate a credential set READ-ONLY against its OANDA host.

    Checks, in order:
      1. account_id prefix must match the account type (101-=practice, 00x-=live);
      2. the token is accepted by that host (GET {api_url}/v3/accounts → 200); and
      3. account_id is actually visible to the token on that host.
    `api_url` overrides the OANDA default host (used by the editable-URL field);
    a non-OANDA URL naturally fails step 2/3 — that is a deliberate guard.
    Returns (ok, message).  Never logs the token."""
    if mode not in MODES:
        return False, f"unknown account type: {mode}"
    if not api_token or not str(api_token).strip():
        return False, "api_token is empty"
    if not account_id or not str(account_id).strip():
        return False, "account_id is empty"

    ptype = account_prefix_type(account_id)
    if ptype is None:
        return False, (f"account_id '{account_id}' has no recognised OANDA prefix "
                       f"(practice=101-, live=00x-)")
    if ptype != mode:
        return False, (f"account_id prefix indicates a {ptype.upper()} account but it "
                       f"was filed under {mode.upper()} — refusing the mismatch")

    host = (api_url or default_url_for(mode)).rstrip("/")
    try:
        ids = _fetch_account_ids(host, api_token)
    except urllib.error.HTTPError as exc:
        return False, f"token rejected by {host} (HTTP {exc.code})"
    except Exception as exc:
        return False, f"could not reach {host}: {exc}"

    if account_id not in ids:
        return False, (f"account_id '{account_id}' is not visible to this token on "
                       f"{mode.upper()} (token can see: {', '.join(ids) or 'none'})")
    return True, "verified"


# ── Status (used by GET /api/credentials) ─────────────────────────────────────
def status() -> dict:
    """Dashboard-safe credential status — booleans + masked last4 only, never
    a token value."""
    local = load_local()
    mode = local.get("mode", "practice")
    if mode not in MODES:
        mode = "practice"

    def _one(kind: str) -> dict:
        c = local.get(kind) or {}
        tok = c.get("api_token")
        acct = c.get("account_id")
        return {
            "configured":      bool(tok and acct),
            "masked":          mask(tok),
            "account_id_last4": ("…" + str(acct)[-4:]) if acct else "—",
            # api_url is NOT a secret — surface it so the field pre-fills + shows
            # any override. Falls back to the OANDA default for the type.
            "api_url":         url_for_set(c, kind),
            "default_url":     default_url_for(kind),
            "url_is_default":  url_for_set(c, kind) == default_url_for(kind),
        }

    resolved = resolve_oanda_creds()
    return {
        "mode":        mode,
        "live_armed":  allow_live(),
        "practice":    _one("practice"),
        "live":        _one("live"),
        "source":      resolved.get("_source"),
        "restart_required_note": ("Broker credentials load at engine start; a mode "
                                  "or credential change applies on the next restart."),
    }
