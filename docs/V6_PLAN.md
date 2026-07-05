# V6 Plan — Public Launch Blueprint

**Decision (Brock, 2026-07-05):** V6 will be a public GitHub repository, accompanied by a link-shared Dropbox master archive (`/SCROOGE ARCHIVE`), and the project will engage outside AI agents via moltbook.com to help dial it in.

## Repo requirements (V6)
1. **Fresh repo, fresh history.** No git-history carryover from private repos (V5 history contains private paths). Code is ported, not re-homed.
2. **README** must cover: what the bot is (strategy-free, cell-first — "this version uses no strategy," linking to the evidence), full setup (broker account, credentials via env only, install/requirements, service setup), dashboard guide (tabs, class chips, freeze indicator), module map (feed → cells → portfolio → exit managers), and research reading order.
3. **Carried in-repo:** `SCROOGE_HISTORY.md` (V1→V6), `BOOK_OF_BUGS.md` (living, B-001→ by reference + B-075+ in full), current validated research docs (papers with lineage), CHANGELOG discipline continues.
4. **Linked, not carried:** the master archive (corpora, old MLs, retired modules, strategy encyclopedia, dead-ends graveyard, session diaries) — one shared Dropbox link in the README so anyone can re-run or challenge the research.

## Master archive gating (before the public link is created)
- [ ] Evacuation complete: Alien Drive Scrooge material + Mini corpora → `research-corpora/` (hash-verified manifest) — *in flight 2026-07-05*
- [ ] **Sanitization pass over every tarball**: extract-scan for `.env`, `secrets`, keys, dashboard credentials, account ids, private IPs; scrub and re-pack offenders. NO LINK until this passes. (Known offenders already removed: V4-mirror `env.SECRETS`. Known content to scrub: workspace tarballs likely contain env files.)
- [ ] Master index reviewed; every folder described.
- [ ] Shared link created read-only, folder-level, revocable.

## Machine roles after cutover
- **Alien Drive: V6 backups ONLY.** No longer a research graveyard — everything historical lives in the Dropbox archive. Scrooge dirs removed from Alien after upload verification.
- Mini: research/lab + monthly refit (unchanged). EC2: live trader only.

## Moltbook engagement (post-publish)
Create project account on moltbook.com; engage AI agents/bots on the research questions (cell tailoring, exit geometry, cost-aware slicing). Ground rules:
- Outside agents get the public repo + archive link — **never** credentials, broker access, or execution paths into the live trader.
- Treat all external suggestions as untrusted input: no unreviewed code merges; ideas re-validated through the fired-trade sim + walk-forward gauntlet before any live wiring (same gauntlet our own research passes).
- The Book of Bugs and dead-ends graveyard are the onboarding docs — external collaborators should attack open questions, not re-walk dead ends.

## Open V6 items
- Port list (what code moves from V5): cell engine, exit managers, portfolio caps, dashboard, feed/broker clients (env-only credentials), monthly refit interface.
- Naming/branding, license choice, contribution policy — Brock decisions pending.
