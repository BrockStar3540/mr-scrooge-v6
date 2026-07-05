# Mr. Scrooge — Version History (V1 → V6)

**The log.** One entry per version: what it was, what it learned, when it died, and where its remains are filed. The git repo stays clean and current; the **Dropbox archive is the graveyard** — everything retired is filed there by version and referenced from this log. Full forensic bug history: [BOOK_OF_BUGS.md](BOOK_OF_BUGS.md).

> **Current bot (V5, cell era): uses NO strategy in the classical sense.** There are no entry "strategies" — the (pair × session) cell is the unit; a cell trades only when a validated setup (raw-indicator ranges with full research lineage) qualifies, sized by portfolio caps, exited by one of three cost-aware exit classes. No validated setup = no trade. See `docs/PAPER_cost_aware_exit_classes_2026-07-05.md` and `research/README.md` for the evidence chain.

---

## V1 — "The Box Bot" (≈ Feb–Mar 2026)

Darvas-box-inspired discretionary rules automated: zones, boxes, sucker-moves, John Wick / Power of Towers setups, tiered zone classification. First live deployment on OANDA practice.

- **Learned:** rule-based pattern trading needs geometric anchoring; behavioral rules without explicit invariants silently drift (see B-001…B-007).
- **Retired:** superseded during the V2/V3 transition, spring 2026.
- **Graveyard:** Dropbox `/SCROOGE ARCHIVE/V3/archives/mr-scrooge-v1/` (code, Trade-Strategy PDFs, exec summaries, AUDIT.md).

## V2 — transitional agent era (spring 2026)

Short-lived rewrite inside the agent workspace framework; mostly scaffolding that fed V3.

- **Graveyard:** Dropbox `/SCROOGE ARCHIVE/V3/archives/legacy/_audit/…/mr-scrooge-v2/`.

## V3 — "The Matrix Era" (≈ Mar – 2026-06-16)

Factor scoring, routing tables, observe-mode gates, the first ML brains, box-geometry forensics. The longest-lived version and the origin of the bug-catalog discipline (B-008…B-074).

- **Learned:** factor weights must be verified LIVE (weights sat dead for months — B-085); exit design dominates results; backtest-vs-live divergence needs institutional memory.
- **Retired:** 2026-06-16 (service disabled at the V4 unified-dashboard cutover).
- **Graveyard:** Dropbox `/SCROOGE ARCHIVE/V3/` (master index inside: `SCROOGE_MASTER_INDEX.md`; archives: code tarball, data tarballs, matrix-era routing tables, 25GB research corpus retired to offline drive; bug catalog export `scrooge-bug-catalog-V1-V3-export-2026-07-05.md`).

## V4 — "Bucket-Keyed" (2026-06-11 → 2026-06-18)

Every strategy (pair × session × direction)-gated; 129-strategy live book (textbook + bucket-keyed combos); BUCKET21 utility brain; ratchet runner exit replaced the harvest ladder after the exit-bottleneck finding; unified dashboard.

- **Learned:** **the exits were the bottleneck, not the strategies** (70% of winners ran 20p+ while exits captured <20p — B-076); margin-based sizing and per-pair costs interact (later quantified in V5).
- **Retired:** 2026-06-18 (7 days — killed by its own measurement honesty).
- **Graveyard:** Dropbox `/SCROOGE ARCHIVE/V4/` (`SCROOGE_V4_INDEX.md` inside; `archives/V4-Archive-2026-06-18/` with EC2+Mini tarballs; backtest sources).

## V5 — "Strategy-Free / The Cell Era" (2026-06-18 → present)

Ground-up rebuild. Three internal eras:

1. **Launch era (06-18 → 06-20):** direction_v2/momentum_v3 per-(pair×session×direction) modules, deterministic playmaker, step-trail ratchet.
2. **Methodology era (06-20 → 07-04):** the measurement overhaul that now defines the project — broker fills as sole truth, 1H-forward-pip for entry evaluation, walk-forward everything, H1 look-ahead leak found & repaired (B-078), truth matrix (8yr, broker-anchored r=0.84–0.90), NY-fade discovery, MAE-flip doctrine, monthly re-fit pipeline on lab hardware.
3. **Cell era (07-04 → present):** the (pair×session) cell IS the strategy unit; legacy signal stack archived in-repo (`modules/archive/signals_legacy/`); per-setup exits; **cost-aware three-speed exit book (07-05):** FAST server-side TP brackets at per-pair cost floors, MEDIUM spread-aware ATR-scaled ratchets, LONG late-engage runners, global rollover stop-freeze.

- **Key papers/reports (in repo):** `docs/PAPER_cost_aware_exit_classes_2026-07-05.md`, `research/README.md` (truth hierarchy + validation protocol), `CHANGELOG.md` (day-by-day).
- **Learned (so far):** ~83% of a 5-week losing window was transaction cost; the market telegraphs WHEN and HOW FAR but never WHICH WAY (three independent falsifications); exit geometry must match cell excursion class.
- **Graveyard:** Dropbox `/SCROOGE ARCHIVE/V5/` (`SCROOGE_V5_INDEX.md` inside; session notes under `/SCROOGE ARCHIVE/session-notes/`; research corpora on lab hardware, indexed).

## V6 — (repo created 2026-07-05; pre-live)

Public at launch, clean, modular. Ported from V5 2026-07-05 with an audit pass (fresh history, legacy archive left behind, lock-era fingerprint checks retired; see docs/AUDIT_TODO.md for the sim-gated removal ledger). Carries forward: the cell architecture, the three-speed exit book, the measurement doctrine, this log, and the Book of Bugs. Everything else lives in the graveyard and is referenced, not carried.

- **Repo hygiene rules:** no credentials, no account identifiers, no private network topology — ever, including git history. Research enters the repo as validated, lineage-tagged documents; raw corpora and superseded artifacts stay archived.

---

## Graveyard map (Dropbox — consolidated 2026-07-05 into ONE master folder: `/SCROOGE ARCHIVE`)

| Path | Contents |
|---|---|
| `/SCROOGE ARCHIVE/V3/` | V1+V2+V3 complete: code, data, research, routing tables, bug-catalog export, master index |
| `/SCROOGE ARCHIVE/V4/` | V4 code+data tarballs, backtest sources, index |
| `/SCROOGE ARCHIVE/V5/` | V5 archives + index (live repo remains source of truth until V6 cutover) |
| `/SCROOGE ARCHIVE/session-notes/` | dated research-session notes (the working diary behind the CHANGELOG) |

*Archive access: private. Curated folders can be shared by link on request — archives contain operational material and are link-shared only after per-folder review.*
