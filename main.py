#!/usr/bin/env python3
"""mr-scrooge-v5 — entry point.

Usage:
    python main.py           # dry run (signal only, no orders)
    python main.py --live    # live trading
"""
import logging, sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
)
log = logging.getLogger("v5.main")


def main():
    dry_run = "--live" not in sys.argv
    if dry_run:
        log.info("DRY RUN mode — pass --live to enable order execution")

    from core.feed.oanda import OandaFeed
    from core.broker.oanda import OandaBroker
    from core.engine import Engine

    feed   = OandaFeed()
    broker = OandaBroker()
    engine = Engine(feed=feed, broker=broker, dry_run=dry_run)

    from ops.server import start_dashboard
    import os
    start_dashboard(engine, port=int(os.environ.get("DASHBOARD_PORT", "8084")),
                    host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"))

    engine.run_forever(scan_interval_seconds=300, manage_interval_seconds=5)  # scan per M5 bar; trail stops every 5s (tightened 2026-06-23: catch peak crossings between bands; ratchet MFE was missing trigger boundaries at 30s)


if __name__ == "__main__":
    main()
