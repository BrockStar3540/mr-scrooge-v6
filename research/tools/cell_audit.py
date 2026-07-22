#!/usr/bin/env python3
"""V5 cell audit + LOCKED-cell safety monitor.

Groups every trade by cell (pair x session x traded-direction), ranks by net pips,
and tags LOCKED cells (config/locked_cells.json) with a lock indicator. For each locked
cell it compares POST-LOCK performance to the dialed-in baseline and raises an early
DEGRADING alert so cells can be edited BEFORE they bleed.

Usage:
  cell_audit.py [--since YYYY-MM-DD] [--csv /path/to/oanda_transactions.csv]
Default source = live journal. --csv = OANDA broker export (more complete; use for real audits).
"""
import argparse, csv, json, re, subprocess
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
PIP={"AUD_JPY":0.01,"EUR_JPY":0.01,"USD_JPY":0.01,"AUD_USD":0.0001,"EUR_USD":0.0001,"GBP_USD":0.0001,"USD_CAD":0.0001,"USD_CHF":0.0001}
def sess(h):
    if 7<=h<13: return "london"
    if 13<=h<22: return "ny"
    return "asia"
def from_journal(since):
    ENT=re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO v5\.engine\s+ENTERED (\w+) (long|short) @ ([\d.]+) \| \d+ units \| SL [+-]?[\d.]+p \| trade_id=(\d+)")
    EXI=re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO v5\.engine\s+EXIT.*?trade_id=(\d+) \| approx_net=([+-]?[\d.]+)p")
    raw=subprocess.check_output(["journalctl","--user","-u","mr-scrooge-v6","--since",since,"--no-pager","-o","cat"],text=True)
    ents={}; exts={}
    for l in raw.splitlines():
        if m:=ENT.search(l): ents[m.group(5)]={"utc":datetime.strptime(m.group(1),"%Y-%m-%d %H:%M:%S"),"pair":m.group(2),"dir":m.group(3)}
        elif m:=EXI.search(l): exts[m.group(2)]=float(m.group(3))
    out=[]
    for tid,e in ents.items():
        if tid in exts: out.append({"pair":e["pair"],"utc":e["utc"],"dir":e["dir"],"pips":exts[tid],"usd":None})
    return out
def from_csv(path):
    rows=list(csv.reader(open(path)))[1:]
    def n(x):
        try: return float(x)
        except: return None
    def utc(s):
        b,off=s.rsplit(" ",1); return datetime.strptime(b,"%Y-%m-%d %H:%M:%S")-timedelta(hours=int(off))
    op={}; out=[]
    for r in rows:
        ttype,det,inst,price,dirn,pl=r[2],r[3],r[4].replace("/","_"),n(r[5]),r[7],n(r[17])
        if ttype!="ORDER_FILL" or not inst: continue
        is_close=(det in ("STOP_LOSS_ORDER","MARKET_ORDER_POSITION_CLOSEOUT","TAKE_PROFIT_ORDER")) or (pl not in (None,0.0) and det!="MARKET_ORDER")
        if det=="MARKET_ORDER" and pl in (None,0.0):
            op[inst]={"utc":utc(r[1]),"dir":"long" if dirn=="Buy" else "short","price":price}
        elif is_close and inst in op:
            o=op.pop(inst); pips=(price-o["price"])/PIP[inst] if o["dir"]=="long" else (o["price"]-price)/PIP[inst]
            out.append({"pair":inst,"utc":o["utc"],"dir":o["dir"],"pips":pips,"usd":pl or 0.0})
    return out

ap=argparse.ArgumentParser(); ap.add_argument("--since",default="2026-06-22"); ap.add_argument("--csv")
a=ap.parse_args()
lk=json.load(open(REPO/"config/locked_cells.json"))
LOCK={(c["pair"],c["session"],c["dir"]):c for c in lk["cells"]}
lock_dt=datetime.strptime(lk.get("lock_ts",lk["lock_date"]+"T00:00:00Z"),"%Y-%m-%dT%H:%M:%SZ")
rules=lk["alert_rules"]
trades=from_csv(a.csv) if a.csv else from_journal(a.since)
trades=[t for t in trades if t["utc"]>=datetime.strptime(a.since,"%Y-%m-%d")]
cells=defaultdict(list)
for t in trades: cells[(t["pair"],sess(t["utc"].hour),t["dir"])].append(t)

# ---- LOCKED CELL SAFETY MONITOR ----
print("="*74); print(f"  LOCKED CELLS — safety monitor (locked {lk['lock_date']}, source={'broker CSV' if a.csv else 'journal'})"); print("="*74)
for key,meta in LOCK.items():
    p,s,d=key; b=meta["baseline"]
    post=sorted([t for t in cells.get(key,[]) if t["utc"]>=lock_dt], key=lambda t:t["utc"])
    tag="🔒 LOCKED"
    if not post:
        status="HOLDING — no new trades since lock (monitoring)"
    else:
        npips=sum(t["pips"] for t in post); w=sum(1 for t in post if t["pips"]>0); wr=100*w/len(post)
        cons=0
        for t in reversed(post):
            if t["pips"]<=0: cons+=1
            else: break
        deg = npips<rules["alert_net_pips_below"] or (len(post)>=2 and wr<rules["min_wr_pct"]) or cons>=rules["consecutive_losses"]
        flag="⚠️  DEGRADING" if deg else "✅ HOLDING"
        status=f"{flag} | post-lock n={len(post)} WR={wr:.0f}% net={npips:+.1f}p (last {cons} losing)"
    print(f"{tag} {p}/{s}/{d:<5} | baseline {b['n']}t {b['wr']}%WR {b['net_pips']:+.1f}p ${b['net_usd']:+.0f} -> {status}")
print("="*74+"\n")

# ---- FULL AUDIT ----
rows=[]
for key,ts in cells.items():
    npips=sum(t["pips"] for t in ts); usd=sum((t["usd"] or 0) for t in ts); w=sum(1 for t in ts if t["pips"]>0)
    rows.append((key,len(ts),w,len(ts)-w,npips,usd,key in LOCK))
rows.sort(key=lambda x:-x[4])
print(f"{'':2}{'pair':<8} {'sess':<7} {'dir':<6} {'n':>3} {'W':>3} {'L':>3} {'WR%':>4} {'net_pips':>9} {'net_$':>8}")
print("-"*66)
for key,nn,w,l,np_,usd,locked in rows:
    p,s,d=key; lk_tag="🔒" if locked else "  "
    print(f"{lk_tag}{p:<8} {s:<7} {d:<6} {nn:>3} {w:>3} {l:>3} {100*w/nn:>4.0f} {np_:>+9.1f} {usd:>+8.0f}")
