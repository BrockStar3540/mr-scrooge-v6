"""tests/test_credentials.py — CONNECTION tab: credential save + practice/live
mode toggle guardrails.

The OANDA network call (_fetch_account_ids) is monkeypatched — no real HTTP.
"""
import json
import urllib.error

import pytest

from config import credentials as cred
from ops import server


@pytest.fixture
def creds_path(tmp_path, monkeypatch):
    p = tmp_path / "credentials.local.json"
    monkeypatch.setattr(cred, "CREDS_PATH", p)
    return p


@pytest.fixture
def fake_oanda(monkeypatch):
    """Make the token verifier see exactly the ids we register per host."""
    registry = {"practice": set(), "live": set()}

    def _fake_fetch(host, token):
        if "reject" in token:
            raise urllib.error.HTTPError(host, 401, "Unauthorized", {}, None)
        mode = "practice" if "fxpractice" in host else "live"
        # token "good:<id>" advertises that id on its host
        if token.startswith("good:"):
            return [token.split(":", 1)[1]]
        return list(registry[mode])

    monkeypatch.setattr(cred, "_fetch_account_ids", _fake_fetch)
    return registry


# ── prefix typing ─────────────────────────────────────────────────────────────
def test_account_prefix_type():
    assert cred.account_prefix_type("101-001-123-000") == "practice"
    assert cred.account_prefix_type("001-001-123-002") == "live"
    assert cred.account_prefix_type("002-001-123-000") == "live"
    assert cred.account_prefix_type("999-xxx") is None
    assert cred.account_prefix_type("") is None


# ── token verification ────────────────────────────────────────────────────────
def test_verify_rejects_prefix_type_mismatch(fake_oanda):
    # a practice-prefixed id filed under live must be rejected before any HTTP
    ok, msg = cred.verify_oanda_token("live", "good:101-1", "101-001-1-0")
    assert not ok and "prefix" in msg.lower()


def test_verify_rejects_bad_token(fake_oanda):
    ok, msg = cred.verify_oanda_token("practice", "reject-me", "101-001-1-0")
    assert not ok and "rejected" in msg.lower()


def test_verify_rejects_account_not_visible(fake_oanda):
    ok, msg = cred.verify_oanda_token("practice", "good:101-OTHER", "101-001-1-0")
    assert not ok and "not visible" in msg.lower()


def test_verify_ok(fake_oanda):
    ok, msg = cred.verify_oanda_token("practice", "good:101-001-1-0", "101-001-1-0")
    assert ok and msg == "verified"


# ── POST /api/credentials (server layer) ──────────────────────────────────────
def test_save_credentials_writes_masked_never_token(creds_path, fake_oanda):
    tok = "good:101-001-1-0"
    out = server._save_credentials({"account": "practice",
                                    "api_token": tok,
                                    "account_id": "101-001-1-0"})
    assert out["ok"] and out["verified"] and out["masked"] == cred.mask(tok)
    assert out["masked"].startswith("…")
    assert "api_token" not in out and "good:" not in json.dumps(out)
    on_disk = json.loads(creds_path.read_text())
    assert on_disk["practice"]["account_id"] == "101-001-1-0"
    assert on_disk["mode"] == "practice"


def test_save_credentials_rejects_type_mismatch(creds_path, fake_oanda):
    with pytest.raises(ValueError):
        server._save_credentials({"account": "live",           # filed live…
                                  "api_token": "good:101-1",
                                  "account_id": "101-001-1-0"})  # …but practice id


def test_save_preserves_other_set_and_mode(creds_path, fake_oanda):
    cred.write_local({"practice": {"api_token": "p", "account_id": "101-x"},
                      "mode": "practice"})
    server._save_credentials({"account": "live", "api_token": "good:001-001-1-2",
                              "account_id": "001-001-1-2"})
    on_disk = json.loads(creds_path.read_text())
    assert on_disk["practice"] == {"api_token": "p", "account_id": "101-x"}
    assert on_disk["live"]["account_id"] == "001-001-1-2"
    assert on_disk["mode"] == "practice"


# ── POST /api/mode guardrails ──────────────────────────────────────────────────
def test_mode_live_blocked_when_not_armed(creds_path, fake_oanda, monkeypatch):
    monkeypatch.delenv("SCROOGE_ALLOW_LIVE", raising=False)
    code, body = server._set_mode({"mode": "live", "confirm": "TRADE REAL MONEY"})
    assert code == 403 and not body["ok"]
    assert "SCROOGE_ALLOW_LIVE" in body["error"]


def test_mode_live_requires_confirm_string(creds_path, fake_oanda, monkeypatch):
    monkeypatch.setenv("SCROOGE_ALLOW_LIVE", "1")
    cred.write_local({"live": {"api_token": "good:001-001-1-2", "account_id": "001-001-1-2"},
                      "mode": "practice"})
    code, body = server._set_mode({"mode": "live", "confirm": "yes please"})
    assert code == 400 and "confirm" in body["error"].lower()


def test_mode_live_requires_saved_creds(creds_path, fake_oanda, monkeypatch):
    monkeypatch.setenv("SCROOGE_ALLOW_LIVE", "1")
    cred.write_local({"mode": "practice"})   # no live set
    code, body = server._set_mode({"mode": "live", "confirm": "TRADE REAL MONEY"})
    assert code == 400 and "live credentials" in body["error"].lower()


def test_mode_live_success_when_armed_and_confirmed(creds_path, fake_oanda, monkeypatch):
    monkeypatch.setenv("SCROOGE_ALLOW_LIVE", "1")
    cred.write_local({"live": {"api_token": "good:001-001-1-2", "account_id": "001-001-1-2"},
                      "mode": "practice"})
    code, body = server._set_mode({"mode": "live", "confirm": "TRADE REAL MONEY"})
    assert code == 200 and body["ok"] and body["mode"] == "live"
    assert body["restart_required"] is True
    assert json.loads(creds_path.read_text())["mode"] == "live"


def test_mode_practice_always_ok(creds_path, fake_oanda, monkeypatch):
    monkeypatch.delenv("SCROOGE_ALLOW_LIVE", raising=False)
    cred.write_local({"mode": "live"})
    code, body = server._set_mode({"mode": "practice"})
    assert code == 200 and body["mode"] == "practice"
    assert json.loads(creds_path.read_text())["mode"] == "practice"


# ── resolution precedence + arm gate ──────────────────────────────────────────
def test_resolve_live_falls_back_to_practice_when_not_armed(creds_path, monkeypatch):
    monkeypatch.delenv("SCROOGE_ALLOW_LIVE", raising=False)
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.setattr(cred, "_SECRETS_ENV", "/nonexistent/secrets.env")
    cred.write_local({"mode": "live",
                      "practice": {"api_token": "ptok", "account_id": "101-p"},
                      "live": {"api_token": "ltok", "account_id": "001-l"}})
    r = cred.resolve_oanda_creds()
    assert r["OANDA_API_TOKEN"] == "ptok"      # live disabled → practice creds
    assert "fxpractice" in r["OANDA_API_URL"]


def test_resolve_env_wins(creds_path, monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "envtok")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "101-env")
    r = cred.resolve_oanda_creds()
    assert r["OANDA_API_TOKEN"] == "envtok" and r["_source"] == "env"


# ── editable api_url ───────────────────────────────────────────────────────────
def test_api_url_persists_and_round_trips(creds_path, fake_oanda):
    out = server._save_credentials({"account": "practice", "api_token": "good:101-001-1-0",
                                    "account_id": "101-001-1-0",
                                    "api_url": "https://api-fxpractice.oanda.com/"})
    assert out["api_url"] == "https://api-fxpractice.oanda.com"   # trailing slash stripped
    on_disk = json.loads(creds_path.read_text())
    assert on_disk["practice"]["api_url"] == "https://api-fxpractice.oanda.com"
    # status + resolve reflect the stored url
    assert cred.status()["practice"]["api_url"] == "https://api-fxpractice.oanda.com"


def test_missing_api_url_falls_back_to_oanda_default(creds_path, fake_oanda):
    server._save_credentials({"account": "practice", "api_token": "good:101-001-1-0",
                              "account_id": "101-001-1-0"})   # no api_url
    on_disk = json.loads(creds_path.read_text())
    assert on_disk["practice"]["api_url"] == cred.OANDA_PRACTICE_URL
    # a set object with no api_url key at all → default per type
    assert cred.url_for_set({}, "practice") == cred.OANDA_PRACTICE_URL
    assert cred.url_for_set({}, "live") == cred.OANDA_LIVE_URL


def test_malformed_api_url_rejected(creds_path, fake_oanda):
    for bad in ["http://insecure.example.com", "not a url", "ftp://x", "https://has space.com"]:
        with pytest.raises(ValueError):
            server._save_credentials({"account": "practice", "api_token": "good:101-1",
                                      "account_id": "101-001-1-0", "api_url": bad})
    # nothing written after rejects
    assert not creds_path.exists() or "practice" not in json.loads(creds_path.read_text())


def test_reset_restores_oanda_default(creds_path, fake_oanda):
    # save a (valid https) override, then a fresh save without api_url returns to default
    cred.write_local({"practice": {"api_token": "t", "account_id": "101-x",
                                   "api_url": "https://api-fxpractice.oanda.com"}})
    assert cred.url_for_set(cred.load_local()["practice"], "practice") == cred.OANDA_PRACTICE_URL
    assert cred.default_url_for("practice") == cred.OANDA_PRACTICE_URL
    assert cred.default_url_for("live") == cred.OANDA_LIVE_URL


def test_env_url_wins_over_stored(creds_path, monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "envtok")
    monkeypatch.setenv("OANDA_API_URL", "https://env-host.example.com")
    r = cred.resolve_oanda_creds()
    assert r["OANDA_API_URL"] == "https://env-host.example.com" and r["_source"] == "env"


def test_resolve_uses_stored_url_when_present(creds_path, monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.setattr(cred, "_SECRETS_ENV", "/nonexistent/secrets.env")
    cred.write_local({"mode": "practice",
                      "practice": {"api_token": "t", "account_id": "101-p",
                                   "api_url": "https://api-fxpractice.oanda.com"}})
    assert cred.resolve_oanda_creds()["OANDA_API_URL"] == "https://api-fxpractice.oanda.com"


def test_valid_https_url():
    assert cred.valid_https_url("https://api-fxtrade.oanda.com")
    assert not cred.valid_https_url("http://x.com")
    assert not cred.valid_https_url("https://")
    assert not cred.valid_https_url("")
    assert not cred.valid_https_url(None)


# ── the file must never be committable ─────────────────────────────────────────
def test_credentials_local_is_gitignored():
    gi = (cred._REPO_ROOT / ".gitignore").read_text()
    assert "credentials.local.json" in gi
