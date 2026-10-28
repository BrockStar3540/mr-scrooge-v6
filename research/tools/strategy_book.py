#!/usr/bin/env python3
"""research/tools/strategy_book.py — build docs/STRATEGY_BOOK.md, the readable book of every setup family.

Sources (all in this repo except the broker transactions):
  config/cells/*.json                  every setup: conditions, exit, status, the evidence it was wired on
  data/virtual_cycles.json             simulated family cycles per setup (the shadow forward simulator)
  research/registry/registry.json      first seen, ever seated, governor decisions
  OANDA transactions (--txns FILE)     real fills; each opening fill's comment names its setup (`su`), and a
                                       popper names its parent's setup (`psu`)

  python3 research/tools/strategy_book.py --txns txns.json [--out docs/STRATEGY_BOOK.md]

`--txns` is a JSON list of OANDA v20 transactions since the live anchor (the shape the livelog pulls).
"""
import argparse, collections, datetime as dt, glob, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUFFIX = re.compile(r"(_t20s|_g_[a-z0-9]+|_nt|_adx|_m|_v|_t|_counter_(long|short)|_counter|_(long|short)|_lean)$")

INDICATORS = [
    ("Bollinger Bands (M5, 20)", [
        ("bb_pos", "where price sits inside the band: 0 = lower band, 1 = upper band"),
        ("bb_width", "band width in pips (how wide the recent range is)"),
        ("zscore_5m", "standard deviations from the 20-bar mean")]),
    ("Momentum and oscillators", [
        ("rsi14", "RSI, 14 bars"),
        ("willr_m5", "Williams %R on M5, 14 bars: −100 = oversold, 0 = overbought"),
        ("adx14", "ADX, 14 bars: trend strength regardless of direction"),
        ("ret_5m", "the last M5 bar's move in pips (positive = up bar)"),
        ("ret_1h", "the last hour's move in pips"),
        ("h1_ret_4bar", "net move over the last 4 H1 bars, in pips"),
        ("d_ret", "move since today's open, in pips")]),
    ("Trend", [
        ("ema_trend_pips", "fast EMA minus slow EMA on M5, in pips: sign = trend, size = separation"),
        ("trend_4h", "+1 if the last 4 hours went up, −1 if down"),
        ("ema20_1h_dist", "distance from the H1 EMA20, as a fraction of price"),
        ("ema20_dist_pct", "distance from the M5 EMA20, as a fraction of price"),
        ("htf_pct_60", "60-day return"),
        ("efficiency_10", "Kaufman efficiency over 10 bars: 1 = straight line, near 0 = chop")]),
    ("Volatility and volume", [
        ("atr_5m", "ATR on M5, pips"),
        ("atr_1h", "ATR on H1, pips"),
        ("atr_h1_relative", "H1 ATR against its own recent average (1.0 = normal)"),
        ("atr_conc", "M5 ATR ÷ H1 ATR"),
        ("adr_consumed", "today's range ÷ the average daily range (1.0 = a full day's move)"),
        ("rvol_5bar", "last 5 bars' tick volume ÷ the prior 20 bars'"),
        ("spread_pips", "the live spread")]),
    ("Session and day levels", [
        ("ps_pos", "where price sits in the previous session's range: 0 = its low, 1 = its high"),
        ("ps_high_dist / ps_low_dist", "pips from the previous session's high / low"),
        ("orb_pos, orb_hi_dist, orb_lo_dist, orb_range_pips", "the session's opening range (first 15 minutes): position, distance from its high/low, its size"),
        ("pdh_dist / pdl_dist", "pips from the previous day's high / low"),
        ("pwh_dist / pwl_dist", "pips from the previous week's high / low"),
        ("vwap_dist_pips", "pips from the session VWAP"),
        ("kc_up_dist_pips", "pips from the upper Keltner Channel (M5, 20, 2×ATR)")]),
    ("Market structure", [
        ("fvg_bull_dist_pips / fvg_bear_dist_pips", "pips from the nearest untouched fair-value gap (three-candle imbalance)"),
        ("ob_bull_dist_pips / ob_bear_dist_pips", "pips from the origin of the nearest unmitigated impulse move (an 'order block')"),
        ("liq_sweep_low / liq_sweep_high", "how far price pierced a pool of stops below equal lows / above equal highs, then came back")]),
]

DESCRIBE = {
    "echo_box_fade": "Fades a Bollinger Band tag. Long when an M5 bar closes at or below the lower band and the next bar turns up; short at the upper band. Brock's Strategy Book 'echo box' setup, replayed.",
    "mr2_bb_reversion": "Mean reversion from a stretch. Short when price is 1.2+ standard deviations above its M5 mean, in the top fifth of the band, RSI 58+, and the last bar turned down; the mirror for longs.",
    "rg1_range_scalp": "Range scalp at the band edge. Short near the top of the M5 band with RSI 62–80 and a down bar; long at the bottom. Variants add band-width and efficiency filters so it only trades quiet ranges.",
    "ps_ceil_fade": "Fades the previous session's high: short when price is in the top 15% of the prior session's range and has not broken its high.",
    "ps_floor_fade": "Buys the previous session's low: long in the bottom 15% of the prior session's range while that low holds.",
    "shark_fade_mid": "Fades a prior-session extreme, but only on a normal-volatility day (H1 ATR 0.8–1.3× normal) that has already used a quarter of its average range.",
    "fvg_fill": "First revisit of an untouched fair-value gap, with the H1 trend: long at or just above a bullish gap while price is above the H1 EMA20.",
    "orb_fade": "Fades back into the session's 15-minute opening range: long at or just under its low (range 5–40 pips), short at its high.",
    "ninja_flag": "Bull/bear flag: a big 1-hour move (the pole, at the pair's 85th percentile or more), M5 EMAs and the H1 trend aligned, then a quiet, tight pullback on low volume.",
    "shark_momo_run": "Momentum on a hot day: H1 ATR 1.3× normal or more, half to two days' range already used, and the 4-hour trend and M5 EMAs agreeing. Go with it.",
    "trend_pullback": "Buy the dip in an uptrend: 4-hour trend up with real H1 momentum (10+ pips over 4 bars) and M5 Williams %R washed out below −85; the mirror for shorts.",
    "alpha_extended_fade": "Buys a sharp oversold dip in an uptrend: RSI 35 or lower, below the H1 EMA20, last bar up, 4-hour trend up; the mirror for shorts.",
    "ninja_stab_fade": "Fades back off the prior-session low in a calm, choppy market (H1 ATR 0.85× normal or less, low efficiency).",
    "liq_sweep_fade": "Liquidity-sweep reversal: the stops under two or more equal lows get run and price comes back. Buy it; the mirror above equal highs.",
    "ninja_amp_break": "Breakout in a high-volatility regime: H1 ATR 1.25× normal or more, M5 EMAs aligned, price at the prior-session high or low.",
    "ninja_stack_break": "Breakout from compression: EMAs stacked with the H1 trend, volatility near normal, a volume burst (1.35×+) at or through the prior-session high or low.",
    "orb_break": "Opening-range breakout: a fresh close 1–10 pips beyond the session's 15-minute opening range (range 5–40 pips).",
    "impulse_ob": "Order-block continuation: price returns to within 3 pips of the origin of the last unmitigated impulse move, with the M5 trend agreeing.",
    "tc_vwapbb": "Trend pullback to the lower Bollinger Band while price holds above the session VWAP and the H1 EMA20 (open-source TradeClaw rules).",
    "timing_lean_30": "Volatility timing: enters when M5 ATR is in its top quarter for that cell, leaning the cell's historical direction, and holds about 30 minutes.",
    "shark_adr_late": "Late-day continuation: the day has used 90–250% of its average range and is 5+ pips from the open. Keep going the day's way.",
    "es_trend": "Trend-regime entry: ADX 25+, 4-hour trend up, price above the M5 EMA20 (open-source EuroScope rules).",
    "es_breakout": "Breakout above the previous day's high with ADX 20+ and RSI 50+ (EuroScope).",
    "es_meanrev": "Range-regime fade: ADX 20 or less, RSI 68+, price at the upper band. Sell it (EuroScope).",
    "pwh_fade": "Fades the previous week's high: within 5 pips of it with RSI 60+.",
    "pwl_fade": "Buys the previous week's low: within 5 pips of it with RSI 40 or less.",
    "box_pdl": "Previous-day-low break: short once price trades below yesterday's low.",
    "control_atrconc_60": "A control formula: one volatility band (M5 ATR ÷ H1 ATR) and the cell's side, held about an hour. History said it should lose; it stamps to test that.",
    "control_rvol_60": "A control formula: one relative-volume band and the cell's side, held about an hour. History said it should lose; it stamps to test that.",
    "control_atr5m_60": "A control formula: one M5 ATR band and the cell's side, held about an hour. History said it should lose; it stamps to test that.",
    "kc_up": "Leans long 4.6–15 pips under the upper Keltner Channel, with normal-or-better volume and a soft 60-day trend.",
    "regime_short_240": "Short in quiet M5 volatility near the Keltner top while the 60-day trend is falling.",
    "rvol_low_240": "Long when relative volume is in its bottom quarter (a quiet tape) and price is not far above yesterday's low.",
    "kc_breakout": "Long on a push above the upper Keltner Channel in calm H1 volatility, well above yesterday's low.",
    "classic_extension_fade": "Buys an over-extension: below the M5 EMA20 with Williams %R −65 or lower.",
    "ps_floor_break": "Session box break: short once price trades below the previous session's low.",
    "classic_box_fade": "The original box fade: buy a close at or below the lower Bollinger Band.",
    "classic_box_break": "The box fade's opposite-direction twin from the flip era: sell a close at or below the lower band (a breakdown).",
    "willr_recovery": "Short when Williams %R recovers above −50 in calm M5 volatility.",
    "classic_willr_fade": "Sells a Williams %R extreme: overbought (−22 or higher) with a down bar.",
}


def family(sid):
    prev = None
    while prev != sid:
        prev, sid = sid, SUFFIX.sub("", sid)
    return sid


def cond_text(c):
    f, lo, hi = c.get("feature"), c.get("min"), c.get("max")
    if lo is not None and hi is not None:
        return f"`{f}` {lo:g} to {hi:g}"
    if lo is not None:
        return f"`{f}` ≥ {lo:g}"
    if hi is not None:
        return f"`{f}` ≤ {hi:g}"
    return f"`{f}`"


def load(txns_path):
    setups = {}
    for f in sorted(glob.glob(str(ROOT / "config/cells/*.json"))):
        d = json.load(open(f))
        for sess, s in d["sessions"].items():
            for su in s["setups"]:
                setups[f"{d['pair']}|{sess}|{su['id']}"] = dict(su, pair=d["pair"], session=sess, family=family(su["id"]))
    try:
        for k, v in json.load(open(ROOT / "data/virtual_cycles.json")).get("rows", {}).items():
            cell, sid, _ = k.split("|")
            key = "%s|%s|%s" % (*cell.split("/"), sid)
            if key in setups:
                setups[key]["_sim"] = v
    except FileNotFoundError:
        pass
    reg = json.load(open(ROOT / "research/registry/registry.json"))["setups"]
    for k, v in reg.items():
        if k in setups:
            setups[k]["_reg"] = v
    tx = json.load(open(txns_path))
    opened, live = {}, collections.defaultdict(lambda: collections.Counter())
    for t in tx:
        if t.get("type") != "ORDER_FILL":
            continue
        to = t.get("tradeOpened")
        if to:
            try:
                cm = json.loads((to.get("clientExtensions") or {}).get("comment") or "{}")
            except ValueError:
                cm = {}
            opened[to["tradeID"]] = (t["instrument"], cm.get("psu") or cm.get("su"), "psu" in cm,
                                     float(t["price"]), float(to["units"]))
        for c in t.get("tradesClosed") or []:
            o = opened.get(c["tradeID"])
            if not o or not o[1]:
                continue
            inst, sid, pop, px, units = o
            pip = 0.01 if "JPY" in inst else 0.0001
            pips = (1 if units > 0 else -1) * (float(t["price"]) - px) / pip
            L = live[family(sid)]
            L["trades"] += 1; L["poppers"] += int(pop); L["wins"] += int(float(c["realizedPL"]) > 0)
            L["pips"] += pips; L["usd"] += float(c["realizedPL"])
    return setups, live


def build(setups, live, now):
    fams = collections.defaultdict(list)
    for s in setups.values():
        fams[s["family"]].append(s)
    rows = []
    for f, ss in fams.items():
        st = collections.Counter(s["status"] for s in ss)
        sim = [s["_sim"] for s in ss if s.get("_sim") and s["_sim"].get("cycles")]
        cyc = sum(x["cycles"] for x in sim)
        L = live.get(f, collections.Counter())
        rows.append(dict(
            family=f, setups=ss, n=len(ss), status=st, pairs=sorted({s["pair"] for s in ss}),
            sessions=sorted({s["session"] for s in ss}),
            feats=[x for x, _ in collections.Counter(c["feature"] for s in ss for c in s.get("conditions", [])).most_common(6)],
            seated=sum(1 for s in ss if (s.get("_reg") or {}).get("ever_seated")),
            sim_cycles=cyc, sim_wr=(sum(x["cycles"] * (x.get("wr") or 0) for x in sim) / cyc) if cyc else None,
            sim_net=(sum(x["cycles"] * (x.get("net_mean") or 0) for x in sim) / cyc) if cyc else None,
            live=L, sources=collections.Counter((s.get("evidence") or {}).get("source") or "" for s in ss)))
    rows.sort(key=lambda r: (-r["live"].get("trades", 0), -r["n"]))
    tot = collections.Counter()
    for r in rows:
        tot.update(r["live"])
    out = []
    w = out.append
    w("# The Strategy Book")
    w("")
    w(f"*Every strategy Mr. Scrooge V6 has put on trial: what it trades, which indicators it reads, what the backtesting said, "
      f"and how it did with real money. Generated {now:%Y-%m-%d} by [`research/tools/strategy_book.py`]"
      f"(../research/tools/strategy_book.py); rebuild it rather than editing it.*")
    w("")
    w(f"**{len(setups):,} setups in {len(rows)} families**, across 18 pairs and 3 sessions (Asia, London, New York). "
      f"Right now {sum(r['status']['ACTIVE'] for r in rows)} are ACTIVE, {sum(r['status']['PROBE'] for r in rows)} are PROBE, "
      f"{sum(r['status']['SHADOW'] for r in rows):,} are SHADOW and {sum(r['status']['DISABLED'] for r in rows)} are retired. "
      f"{sum(r['seated'] for r in rows)} setups have held a live seat at some point. Since the live cutover on 2026-07-29 the "
      f"account closed {tot['trades']:,} trades attributed to a setup: {tot['pips']:+,.0f} pips, ${tot['usd']:+,.2f} realized.")
    w("")
    w("## How to read this book")
    w("")
    w("- **A setup** is one family's rules on one pair, session and side. Each family is a single idea, so it has dozens of "
      "setups: long and short, a *counter* twin that takes the opposite side, `_t20s` trials with a wider ratchet, and `_g_*` "
      "variants with an extra gate.")
    w("- **SHADOW** setups trade on paper: every time one fires, the bot stamps a simulated trade. **PROBE** setups trade real "
      "money at 0.20× size. **ACTIVE** setups trade full size. How a setup moves between them is in the "
      "[README](../README.md#how-a-setup-keeps-its-seat).")
    w("- **What the backtesting said** is the evidence each family was built on, quoted from the setup files. Many of those "
      "numbers came before fixes we found later (an H1 look-ahead bug fixed 2026-07-03, and simulator costs), so treat them as "
      "the reason a family was tried, not proof it worked.")
    w("- **Simulator** is the shadow forward test: completed family cycles stamped live and scored on the current exit. "
      "Its per-setup correlation with real fills was 0.07, so it is a weak guide.")
    w("- **Real money** is every live trade the family opened, parents and the poppers their grids fired, from the broker's "
      "own fills. Pips include the spread. Dollars depend on position size, which changed over the record; pips compare.")
    w("")
    w("## The short version")
    w("")
    w("| Family | What it does | Reads | Setups now (A / P / S / retired) | Simulator | Real money |")
    w("|---|---|---|---|---|---|")
    for r in rows:
        L, st = r["live"], r["status"]
        sim = (f"{r['sim_cycles']} cyc, {r['sim_wr']:.0%}, {r['sim_net']:+.1f}p" if r["sim_cycles"] else "—")
        lv = (f"{L['trades']} trades, {L['pips']:+,.0f}p, {L['wins'] / L['trades']:.0%} won" if L.get("trades") else "never traded")
        desc = re.split(r"\. |: | \(", DESCRIBE.get(r["family"], ""))[0].rstrip(".")
        w(f"| [{r['family']}](#{r['family']}) | {desc} | {', '.join('`%s`' % f for f in r['feats'][:3])} | "
          f"{st['ACTIVE']} / {st['PROBE']} / {st['SHADOW']} / {st['DISABLED']} | {sim} | {lv} |")
    w("")
    w("## What it all says")
    w("")
    w("- **Nothing yet beats the spread.** Across the live record, OANDA's own half-spread charges came to about three quarters "
      "of the realized loss. Families win often (most real-money families won 70–90% of trades) but their wins are small and "
      "their losses are large, so the win rate does not pay.")
    w("- **The indicators find distance, not direction.** The V1–V4 research found entry features predicted when and how far "
      "price would move, never which way (0 of 144 feature × cell combinations carried direction). The families here are "
      "different ways of asking the same question, and the real-money column is the answer so far.")
    sim_vs = sorted((r for r in rows if r["sim_cycles"] and r["live"].get("trades", 0) >= 15
                     and r["sim_net"] > 0 and r["live"]["pips"] < 0), key=lambda r: -r["sim_net"])[:3]
    w("- **Paper and real money disagree.** Families that looked best in the simulator were often not the ones that made "
      "money, which is why seats are now judged only on broker fills. For example: " + "; ".join(
          f"`{r['family']}` {r['sim_net']:+.1f} pips a cycle in the simulator, {r['live']['pips']:+,.0f} pips over "
          f"{r['live']['trades']} real trades" for r in sim_vs) + ".")
    w("- **The controls are the warning label.** `control_atr5m_60` was built as a control that history said should lose, "
      "and it holds one of the best real-money records in the book. A handful of trades can make any idea look good.")
    w("")
    w("## The indicators")
    w("")
    w("Every setup is a few conditions on these features, computed from OANDA M5, H1 and daily candles at each 5-minute bar "
      "([`core/feed/oanda.py`](../core/feed/oanda.py), [`core/feed/structure.py`](../core/feed/structure.py)).")
    w("")
    for group, items in INDICATORS:
        w(f"**{group}**")
        w("")
        for k, v in items:
            w(f"- `{k}`: {v}")
        w("")
    w("## The families")
    w("")
    for r in rows:
        L, st = r["live"], r["status"]
        rep = min(r["setups"], key=lambda s: (len(s["id"]), s["id"]))
        mirror = next((s for s in r["setups"] if s["side"] != rep["side"] and len(s["id"]) <= len(rep["id"]) + 6), None)
        w(f"### {r['family']}")
        w("")
        w(DESCRIBE.get(r["family"], "(no description yet)"))
        w("")
        w(f"- **Rules, `{rep['id']}`:** " + "; ".join(cond_text(c) for c in rep.get("conditions", [])) +
          f". Holds up to {rep.get('horizon_min')} minutes in the simulator.")
        if mirror:
            w(f"- **Rules, `{mirror['id']}`:** " + "; ".join(cond_text(c) for c in mirror.get("conditions", [])) + ".")
        w(f"- **Where it trades:** {r['n']} setups on {len(r['pairs'])} pairs ({', '.join(r['pairs'][:8])}"
          f"{', …' if len(r['pairs']) > 8 else ''}), sessions: {', '.join(r['sessions'])}.")
        w(f"- **Status now:** {st['ACTIVE']} ACTIVE, {st['PROBE']} PROBE, {st['SHADOW']} SHADOW, {st['DISABLED']} retired. "
          f"{r['seated']} of its setups have held a live seat.")
        src = [s for s, _ in r["sources"].most_common(2) if s]
        if src:
            w("- **What the backtesting said:**")
            for s in src:
                w(f"  - {s[:400]}{'…' if len(s) > 400 else ''}")
        if r["sim_cycles"]:
            w(f"- **Simulator:** {r['sim_cycles']} completed cycles, {r['sim_wr']:.0%} won, {r['sim_net']:+.1f} pips per cycle.")
        else:
            w("- **Simulator:** no completed cycles yet.")
        if L.get("trades"):
            w(f"- **Real money:** {L['trades']} trades ({L['poppers']} of them poppers), {L['pips']:+,.1f} pips "
              f"({L['pips'] / L['trades']:+.2f} per trade), {L['wins'] / L['trades']:.0%} won, ${L['usd']:+,.2f}.")
        else:
            w("- **Real money:** never traded.")
        w("")
    w("## Before V6")
    w("")
    w("V1–V5 tested a different generation of strategies: the box bot, the Trade-Strategy library, bucket-keyed routing and the "
      "strategy-free cell era. They are written up in the archive's "
      "[Strategy Encyclopedia](https://github.com/BrockStar3540/mr-scrooge-archive/blob/main/docs-harvest/v4-repo-docs/STRATEGY_ENCYCLOPEDIA.md) "
      "and [dead-ends graveyard](https://github.com/BrockStar3540/mr-scrooge-archive/blob/main/docs-harvest/v3-repo-docs/history/dead-ends-graveyard.md), "
      "and the edge hunts that falsified them are in [`docs/papers/`](papers/).")
    w("")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--txns", required=True)
    ap.add_argument("--out", default=str(ROOT / "docs/STRATEGY_BOOK.md"))
    a = ap.parse_args()
    s, l = load(a.txns)
    Path(a.out).write_text(build(s, l, dt.datetime.now(dt.timezone.utc)))
    print("wrote", a.out)
