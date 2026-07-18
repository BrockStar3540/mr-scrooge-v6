"""Regression: the feed and the broker must resolve OANDA credentials via the
SAME path (config.credentials.resolve_oanda_creds). A public reviewer found the
feed still read secrets.env-only while the broker used the credential module —
so a dashboard/credentials.local.json clone had a live broker but a blank feed.
"""
import importlib, types

def test_feed_and_broker_both_delegate_to_resolver(monkeypatch):
    import core.feed.oanda as feed
    import core.broker.oanda as broker
    sentinel = {"OANDA_API_URL": "https://x", "OANDA_API_TOKEN": "tok", "OANDA_ACCOUNT_ID": "101-1"}
    called = {"n": 0}
    def fake_resolve():
        called["n"] += 1
        return dict(sentinel)
    import config.credentials as creds
    monkeypatch.setattr(creds, "resolve_oanda_creds", fake_resolve)
    feed._SECRETS_CACHE = None
    assert feed._secrets() == sentinel      # feed now routes through the resolver
    assert broker._secrets() == sentinel    # broker already did
    assert called["n"] >= 2                 # both actually called it
    feed._SECRETS_CACHE = None
