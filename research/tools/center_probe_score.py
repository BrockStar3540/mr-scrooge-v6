#!/usr/bin/env python3
"""research/tools/center_probe_score.py — mine the box-probe log for direction/
breakout filters, grouped by ZONE (center | ceiling | floor).

signed_travel = fwd_up - fwd_down over 240m (which wall the wave rode).
  center : +=rode to ceiling, -=rode to floor  -> which-way filter
  ceiling: +=broke out above, -=reversed down   -> breakout-vs-fade filter
  floor  : +=broke down,      -=bounced up       -> breakdown-vs-bounce filter
Per zone, ranks every indicator by tercile separation of signed_travel.
"""
import os, json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import statistics as st

_c = Path(__file__).resolve().parents[2] / "data" / "center_probe_log.jsonl"
LOG = _c if _c.exists() else Path(os.path.expanduser("~/mr-scrooge-v6/data/center_probe_log.jsonl"))

def creds():
    for line in open(os.path.expanduser("~/.openclaw/secrets.env")):
        line=line.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return (os.environ.get("OANDA_API_URL","https://api-fxpractice.oanda.com").rstrip("/"),
            os.environ["OANDA_API_TOKEN"])

def fwd(url,tok,pair,t0):
    pm=0.01 if "JPY" in pair else 0.0001
    u=f"{url}/v3/instruments/{pair}/candles?granularity=M5&from={t0.strftime('%Y-%m-%dT%H:%M:%SZ')}&count=49&price=M"
    cs=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"Authorization":f"Bearer {tok}"}),timeout=20))["candles"]
    if len(cs)<13: return None
    e=float(cs[0]["mid"]["o"])
    return (max(float(c["mid"]["h"]) for c in cs)-e)/pm - (e-min(float(c["mid"]["l"]) for c in cs))/pm

def main():
    if not LOG.exists(): print("no probe log yet:",LOG); return
    obs=[json.loads(l) for l in open(LOG) if l.strip()]
    from collections import Counter
    print(f"observations: {len(obs)} | by zone: {dict(Counter(o.get('zone','?') for o in obs))}")
    url,tok=creds(); now=datetime.now(timezone.utc); scored=[]
    for o in obs:
        t0=datetime.fromisoformat(o["ts"])
        if (now-t0).total_seconds() < 245*60: continue
        try:
            s=fwd(url,tok,o["pair"],t0)
            if s is not None: o["st"]=s; scored.append(o); time.sleep(0.04)
        except Exception: continue
    print(f"matured & scored: {len(scored)}")
    try: from scipy.stats import spearmanr
    except Exception: spearmanr=None
    for zone in ("center","ceiling","floor"):
        z=[o for o in scored if o.get("zone")==zone]
        if len(z) < 30:
            print(f"\n== {zone.upper()} == n={len(z)} (insufficient, target >=60)"); continue
        y=[o["st"] for o in z]
        pos_label = {"center":"rode UP","ceiling":"broke OUT","floor":"broke DOWN"}[zone]
        print(f"\n== {zone.upper()} == n={len(z)} | {sum(1 for v in y if v>0)}/{len(y)} {pos_label} | median travel {st.median(y):+.1f}p")
        feats=[k for k in z[0] if k not in ("ts","pair","session","zone","mid","box","st") and z[0][k] is not None]
        rows=[]
        for f in feats:
            xs=[(o[f],o["st"]) for o in z if isinstance(o.get(f),(int,float))]
            if len(xs)<30: continue
            r=spearmanr([a for a,_ in xs],[b for _,b in xs]).statistic if spearmanr else 0.0
            xs.sort(); k=max(1,len(xs)//3)
            lo=st.mean(b for _,b in xs[:k]); hi=st.mean(b for _,b in xs[-k:])
            rows.append((abs(hi-lo),f,r,lo,hi))
        for sep,f,r,lo,hi in sorted(rows,reverse=True)[:8]:
            print(f"   {f:20} rho {r:+.3f} | low3 {lo:+6.1f}  high3 {hi:+6.1f}  spread {hi-lo:+6.1f}p")
    print("\nSeparator = rho>|0.15| + monotone spread. Center->which-way; ceiling/floor->breakout-vs-reversal.")

if __name__=="__main__": main()
