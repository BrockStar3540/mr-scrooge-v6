# Deployment

V6 runs as a single long-lived process on any Linux host (2GB RAM is plenty; the
bot is I/O-bound). Reference deployment: a small cloud VM running the user
systemd unit in `ops/mr-scrooge-v6.service`.

## Layout
- Repo checkout at `~/mr-scrooge-v6`, run as an unprivileged user.
- Credentials in a chmod-600 env file OUTSIDE the repo (see `.env.example`),
  loaded into the service environment — never in code, configs, or git.
- `data/` is runtime scratch (journal, caches) and is gitignored.

## Service
```
systemctl --user enable --now mr-scrooge-v6   # after copying ops/mr-scrooge-v6.service
journalctl --user -u mr-scrooge-v6 -f         # logs
```

## Operational rules (earned the hard way — see docs/BOOK_OF_BUGS.md)
1. **The live host runs the trader and nothing heavy.** Research/backtests run
   elsewhere; an OOM on the trader box during open positions is a real incident
   class (B-era lesson, 2026-06-12).
2. **Verify archives before deleting sources** (`gzip -t` + member counts +
   content hashes) — B-083.
3. **Broker fills are the only trade truth.** The journal logs intent; audits
   and P/L analysis go through the broker API.
4. Deploy = commit + push + restart + verify first cycle in the journal +
   update the CHANGELOG. The dashboard HEALTH tab should be green before you
   walk away.

## Monitoring
- Dashboard `:8084` — LIVE positions w/ exit-class management, BOOK cell state,
  HEALTH service checks.
- The engine logs one `CYCLE` line per scan; silence >10 min = investigate.
