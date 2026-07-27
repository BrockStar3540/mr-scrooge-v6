"""tests/test_dashboard_origin.py — mutating endpoints reject cross-origin.

External-review finding (2026-07-27): the dashboard sent
Access-Control-Allow-Origin:* on unauthenticated write endpoints — any webpage
the operator visits could script POSTs at localhost:8084. The wildcard is gone
and every POST passes a same-origin guard: no Origin header (curl, same-machine
tools) is allowed; a present Origin must match the Host header exactly.
"""
from types import SimpleNamespace

from ops.server import _Handler


def _allowed(headers: dict) -> bool:
    fake = SimpleNamespace(headers=headers)
    return _Handler._write_allowed(fake)


def test_no_origin_header_allowed():
    assert _allowed({"Host": "127.0.0.1:8084"})


def test_same_origin_allowed():
    assert _allowed({"Host": "127.0.0.1:8084",
                     "Origin": "http://127.0.0.1:8084"})
    assert _allowed({"Host": "localhost:8084",
                     "Origin": "http://localhost:8084"})


def test_cross_origin_rejected():
    assert not _allowed({"Host": "127.0.0.1:8084",
                         "Origin": "http://evil.example"})
    assert not _allowed({"Host": "127.0.0.1:8084",
                         "Origin": "https://evil.example:8084"})


def test_dns_rebinding_rejected():
    # attacker's domain resolves to 127.0.0.1: Host says localhost, but the
    # browser still reports the attacker origin — must be rejected
    assert not _allowed({"Host": "127.0.0.1:8084",
                         "Origin": "http://rebind.attacker.tld:8084"})


def test_origin_present_but_no_host_rejected():
    assert not _allowed({"Origin": "http://127.0.0.1:8084"})


def test_garbage_origin_rejected():
    assert not _allowed({"Host": "127.0.0.1:8084", "Origin": "\x00://:::"})


def test_cors_wildcard_is_gone():
    import inspect
    import ops.server as srv
    src = inspect.getsource(srv)
    assert 'send_header("Access-Control-Allow-Origin", "*")' not in src
