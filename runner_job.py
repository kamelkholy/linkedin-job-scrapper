#!/usr/bin/env python3
"""One-shot entrypoint for the Azure Container Apps Job.

Runs the multi-location scrape once, persists results, and exits with a
non-zero code on failure so the platform records the failure correctly.
"""

from __future__ import annotations

import logging
import sys

import db
import scheduler


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    log = logging.getLogger("runner_job")
    log.info("Container Apps Job started.")

    db.init_db()

    try:
        summary = scheduler.run_scrape_now()
    except RuntimeError as exc:
        log.error("Could not start scrape: %s", exc)
        return 2

    if summary.get("error"):
        log.error("Scrape finished with errors: %s", summary["error"])
        return 1

    log.info(
        "Scrape complete — new=%s updated=%s seen=%s",
        summary.get("new"), summary.get("updated"), summary.get("seen"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
