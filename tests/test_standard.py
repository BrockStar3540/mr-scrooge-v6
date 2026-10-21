from ops.standard import broker_veto, cycle_stats, merged, pick_auditions, verdict, window

CFG = {"enabled": True}


def cyc(pips, start_day=1):
    return [{"pips": p, "end": f"2026-10-{start_day + i:02d}T10:00"} for i, p in enumerate(pips)]


def test_stats_profit_factor_and_worst():
    s = cycle_stats([10, 10, -5])
    assert s["n"] == 3 and abs(s["wr"] - 2 / 3) < 1e-9 and s["pf"] == 4.0 and s["worst"] == -5


def test_window_keeps_last_n_completed_by_end_time():
    c = cyc([1, 2, 3]) + [{"pips": 99, "end": None}]
    assert window(c, 2) == [2.0, 3.0]


def test_top5_style_setup_stays():
    # classic_willr-like: 19 wins of ~+12p, one -12p loss
    a, why = verdict("ACTIVE", cyc([12] * 19 + [-12]), CFG)
    assert a == "KEEP", why


def test_high_win_rate_but_thin_edge_demotes():
    # orb_fade_short-like: 88% wins but +0.3p/cycle
    a, why = verdict("ACTIVE", cyc([6.5] * 15 + [-45, -50]), CFG)
    assert a == "DEMOTE" and "STAY" in why


def test_tripwire_fires_even_on_tiny_sample():
    a, why = verdict("ACTIVE", cyc([8, 8, -92.1]), CFG)
    assert a == "DEMOTE" and "TRIPWIRE" in why


def test_too_few_cycles_keeps():
    a, _ = verdict("ACTIVE", cyc([8, -50, 8]), CFG)
    assert a == "KEEP"


def test_no_fills_keeps():
    assert verdict("ACTIVE", [], CFG)[0] == "KEEP"


def test_probe_graduates_on_top5_profile():
    a, _ = verdict("PROBE", cyc([10] * 9 + [-20]), CFG)
    assert a == "GRADUATE"


def test_probe_that_only_stays_is_held_then_cut_at_limit():
    ok_not_great = [6] * 8 + [-12, -12]          # wr 80%, +2.4p? -> below stay exp
    assert verdict("PROBE", cyc(ok_not_great), CFG)[0] == "DEMOTE"
    stays = [8] * 9 + [-30]                       # wr 90%, +4.2p, pf 2.4 -> stay, not enter
    assert verdict("PROBE", cyc(stays), CFG)[0] == "KEEP"
    assert verdict("PROBE", cyc(stays * 2), CFG)[0] == "DEMOTE"   # 20 cycles, never met enter


def test_merged_overrides_nested_floor_only():
    m = merged({"stay": {"wr": 0.9}})
    assert m["stay"]["wr"] == 0.9 and m["stay"]["pf"] == 1.5 and m["window_cycles"] == 20


def test_auditions_filter_cooldown_strikes_and_one_per_pair_side():
    base = {"strikes_ok": True, "cooldown": False, "pair_side_seated": False,
            "sim_cycles": 10, "sim_wr": 0.9}
    cands = [
        {**base, "key": ("EUR_USD", "ny", "a"), "side": "long", "sim_net": 9},
        {**base, "key": ("EUR_USD", "london", "b"), "side": "long", "sim_net": 8},   # same pair+side
        {**base, "key": ("GBP_USD", "ny", "c"), "side": "short", "sim_net": 7, "cooldown": True},
        {**base, "key": ("USD_JPY", "ny", "d"), "side": "short", "sim_net": 6, "strikes_ok": False},
        {**base, "key": ("AUD_USD", "asia", "e"), "side": "long", "sim_net": 5, "sim_wr": 0.7},
        {**base, "key": ("NZD_USD", "asia", "f"), "side": "short", "sim_net": 4},
    ]
    got = [x["key"][2] for x in pick_auditions(cands, 3, CFG)]
    assert got == ["a", "f"]
    assert pick_auditions(cands, 0, CFG) == []


def test_broker_record_vetoes_audition():
    assert broker_veto(cyc([8, 8, -92]), CFG)               # tripwire
    assert broker_veto(cyc([5, -30]), CFG)                   # net negative
    assert broker_veto(cyc([6.5] * 15 + [-45, -50]), CFG)    # judgeable, fails STAY
    assert not broker_veto([], CFG)                          # never traded: sim may queue it
    assert not broker_veto(cyc([8, 8, -10]), CFG)            # small, net positive
    base = {"strikes_ok": True, "cooldown": False, "pair_side_seated": False,
            "sim_cycles": 10, "sim_wr": 0.9, "side": "long"}
    cands = [{**base, "key": ("USD_CAD", "london", "x"), "sim_net": 9, "broker_cycles": cyc([8, -92])},
             {**base, "key": ("EUR_CAD", "asia", "y"), "sim_net": 5}]
    assert [x["key"][2] for x in pick_auditions(cands, 3, CFG)] == ["y"]
