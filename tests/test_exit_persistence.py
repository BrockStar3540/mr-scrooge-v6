"""Exit-gear persistence via OANDA tradeClientExtensions (AUDIT_TODO item).

A restart must hand a recovered trade its ENTRY gear, not exit_config
defaults (2026-07-15 frozen-gear straggler lesson)."""
import json

from core.engine import _decode_exit_ext, _encode_exit_ext
from modules.cells.cell import ExitParams


def _ep(**kw):
    base = dict(sl_pips=40.0, trigger_pips=7.5, trail_pips=2.5)
    base.update(kw)
    return ExitParams(**base)


def test_round_trip_ratchet():
    ep = _ep(trail_mult=0.0, trail_min=2.5, trail_max=10.0)
    ext = _encode_exit_ext(ep, "kc_up_long_lean")
    got, setup = _decode_exit_ext({"clientExtensions": ext})
    assert setup == "kc_up_long_lean"
    assert (got.sl_pips, got.trigger_pips, got.trail_pips) == (40.0, 7.5, 2.5)
    assert got.mode == "ratchet" and got.trail_mult == 0.0
    assert (got.trail_min, got.trail_max) == (2.5, 10.0)


def test_round_trip_bracket():
    ep = _ep(mode="bracket", tp_pips=5.0, timeout_min=60.0)
    got, _ = _decode_exit_ext({"clientExtensions": _encode_exit_ext(ep, "fast_slice")})
    assert got.mode == "bracket"
    assert got.tp_pips == 5.0 and got.timeout_min == 60.0


def test_comment_fits_oanda_128_char_limit():
    ep = _ep(trail_mult=1.0, trail_min=2.5, trail_max=10.0,
             tp_pips=5.0, timeout_min=60.0, mode="bracket")
    ext = _encode_exit_ext(ep, "classic_extension_fade_long_with_a_very_long_name")
    assert len(ext["comment"]) <= 128
    # gear must survive even if the setup id was dropped for length
    got, _ = _decode_exit_ext({"clientExtensions": ext})
    assert got.sl_pips == 40.0


def test_decode_rejects_foreign_and_garbage():
    assert _decode_exit_ext({}) is None
    assert _decode_exit_ext({"clientExtensions": {"comment": "manual close pls"}}) is None
    assert _decode_exit_ext({"clientExtensions": {"comment": "{not json"}}) is None
    assert _decode_exit_ext({"clientExtensions": {"comment": json.dumps({"m": "ratchet"})}}) is None  # missing gear keys
