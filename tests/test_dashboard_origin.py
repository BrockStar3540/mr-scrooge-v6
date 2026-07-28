"""tests/test_dashboard_origin.py — dashboard security model (review round 2).

Three gates on every mutation, in order: Host allowlist (membership beats DNS
rebinding, where Origin==Host equality passes), Origin allowlist (no-Origin
tools must come from a loopback peer), constant-time token auth (mandatory for
any non-loopback bind, optional-but-honored on loopback). Plus: the credential
verifier may only ever transmit a bearer token to official OANDA hosts.
"""
from types import SimpleNamespace

import pytest

from ops.server import (_Handler, allowed_oanda_api_url,
                        dashboard_allowed_hosts)

ALLOW = {"localhost:8084", "127.0.0.1:8084", "[::1]:8084"}


def _fake(headers=None, peer="127.0.0.1", allowed=ALLOW):
    return SimpleNamespace(headers=headers or {},
                           client_address=(peer, 55555),
                           server=SimpleNamespace(allowed_hosts=allowed))


# ── host allowlist ───────────────────────────────────────────────────────────

def test_allowed_host_passes():
    f = _fake({"Host": "127.0.0.1:8084"})
    assert _Handler._host_allowed(f)


def test_dns_rebinding_host_rejected():
    # attacker domain resolves to 127.0.0.1: Origin==Host equality would pass,
    # allowlist membership does not
    f = _fake({"Host": "rebind.attacker.tld:8084",
               "Origin": "http://rebind.attacker.tld:8084"})
    assert not _Handler._host_allowed(f)


def test_loopback_defaults_and_configured_hosts(monkeypatch):
    monkeypatch.delenv("DASHBOARD_ALLOWED_HOSTS", raising=False)
    d = dashboard_allowed_hosts("127.0.0.1", 8084)
    assert "127.0.0.1:8084" in d and "localhost:8084" in d
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", "panel.lan:8084")
    d2 = dashboard_allowed_hosts("0.0.0.0", 8084)
    assert d2 == {"panel.lan:8084"}, "non-loopback binds get ONLY configured hosts"


# ── origin ───────────────────────────────────────────────────────────────────

def test_same_origin_allowed():
    f = _fake({"Host": "127.0.0.1:8084", "Origin": "http://127.0.0.1:8084"})
    assert _Handler._origin_allowed(f)


def test_cross_origin_rejected():
    f = _fake({"Host": "127.0.0.1:8084", "Origin": "http://evil.example"})
    assert not _Handler._origin_allowed(f)


def test_no_origin_requires_loopback_peer():
    assert _Handler._origin_allowed(_fake({"Host": "127.0.0.1:8084"}))
    lan = _fake({"Host": "127.0.0.1:8084"}, peer="192.168.1.50")
    assert not _Handler._origin_allowed(lan), \
        "a headerless LAN request must not bypass the origin gate"


def test_garbage_origin_rejected():
    f = _fake({"Host": "127.0.0.1:8084", "Origin": "\x00://:::"})
    assert not _Handler._origin_allowed(f)


# ── auth ─────────────────────────────────────────────────────────────────────

def test_no_token_configured_is_open_on_loopback(monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    assert _Handler._authenticated(_fake())


def test_wrong_and_right_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "sekrit-token-of-adequate-length")
    assert not _Handler._authenticated(_fake({}))
    assert not _Handler._authenticated(_fake({"X-Scrooge-Token": "wrong"}))
    assert _Handler._authenticated(
        _fake({"X-Scrooge-Token": "sekrit-token-of-adequate-length"}))


def test_token_uses_constant_time_compare():
    import inspect
    import ops.server as srv
    src = inspect.getsource(srv._Handler._authenticated)
    assert "compare_digest" in src


# ── OANDA API host allowlist (token-exfiltration fix) ────────────────────────

def test_official_hosts_accepted():
    assert allowed_oanda_api_url("https://api-fxpractice.oanda.com", "practice")
    assert allowed_oanda_api_url("https://api-fxtrade.oanda.com", "live")


def test_cross_mode_and_arbitrary_hosts_rejected(monkeypatch):
    monkeypatch.delenv("SCROOGE_OANDA_HOST_ALLOWLIST", raising=False)
    assert not allowed_oanda_api_url("https://api-fxtrade.oanda.com", "practice")
    assert not allowed_oanda_api_url("https://api-fxpractice.oanda.com", "live")
    assert not allowed_oanda_api_url("https://evil.example", "practice")
    assert not allowed_oanda_api_url("https://api-fxpractice.oanda.com.evil.tld",
                                     "practice")


def test_startup_allowlist_extends(monkeypatch):
    monkeypatch.setenv("SCROOGE_OANDA_HOST_ALLOWLIST",
                       "https://mock.internal.example")
    assert allowed_oanda_api_url("https://mock.internal.example", "practice")


def test_cors_wildcard_never_returns():
    import inspect
    import ops.server as srv
    assert 'send_header("Access-Control-Allow-Origin", "*")' not in inspect.getsource(srv)
