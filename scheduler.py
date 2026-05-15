"""Background scheduler — runs the multi-location scrape once a day.

Uses APScheduler's BackgroundScheduler so it lives in the Flask process.
Settings (locations, schedule time, etc.) are read from the TinyDB
`settings` table on every run — so changes from the web UI take effect on
the next run without restarting the server.

When deployed to Azure, the in-process scheduler is disabled (set env var
DISABLE_SCHEDULER=1) and a separate Container Apps Job invokes the
`run_scrape_now()` function on a cron schedule managed by Azure.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

try:
    from zoneinfo import ZoneInfo
    _UTC = ZoneInfo("UTC")
except ImportError:  # < Py3.9 fallback
    from datetime import timezone as _tz
    _UTC = _tz.utc

import db
from filters import filter_jobs
from remote_scraper import RemoteJobScraper
from scraper import Job, LinkedInScraper

logger = logging.getLogger(__name__)


def _scheduler_disabled() -> bool:
    return os.environ.get("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes")

JOB_ID = "daily-scrape"

_scheduler: BackgroundScheduler | None = None
_run_lock = threading.Lock()
_state = {
    "running": False,
    "kind": None,            # "linkedin" | "remote"
    "progress": "",
    "current_location": "",
    "current_company": "",
    "started_at": None,
    "finished_at": None,
    "last_error": None,
    "summary": None,  # last run summary dict
}
_state_lock = threading.Lock()


# ── State helpers ─────────────────────────────────────────────────────────

def get_state() -> dict:
    with _state_lock:
        return dict(_state)


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


# ── Core: one scrape over all locations ───────────────────────────────────

def run_scrape_now(progress_cb: Callable[[str], None] | None = None) -> dict:
    """Run a multi-location scrape immediately. Thread-safe (single-flight).

    Returns the run summary dict that was persisted to the `runs` table.
    """
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("A scrape is already running.")
    try:
        return _do_run(progress_cb)
    finally:
        _run_lock.release()


def _do_run(progress_cb: Callable[[str], None] | None) -> dict:
    settings = db.get_settings()
    locations = settings.get("locations") or [""]
    if not locations:
        locations = [""]

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _set_state(
        running=True,
        kind="linkedin",
        progress="Starting daily scrape…",
        current_location="",
        current_company="",
        started_at=started_at,
        finished_at=None,
        last_error=None,
        summary=None,
    )
    logger.info("=== Daily scrape started — %d location(s) ===", len(locations))

    per_location: list[dict] = []
    total_new = 0
    total_updated = 0
    total_seen = 0
    error: str | None = None

    try:
        for idx, loc in enumerate(locations, 1):
            label = loc or "(worldwide)"
            msg = f"[{idx}/{len(locations)}] Scraping {label}…"
            logger.info(msg)
            _set_state(progress=msg, current_location=label)
            if progress_cb:
                progress_cb(msg)

            scraper = LinkedInScraper(
                keywords=settings.get("keywords"),
                location=loc,
                geo_id=settings.get("geo_id", ""),
                max_pages=int(settings.get("max_pages", 10)),
                skip_details=bool(settings.get("skip_details", False)),
            )
            try:
                raw_jobs: list[Job] = scraper.scrape()
            finally:
                scraper.close()

            if settings.get("no_filter"):
                kept = raw_jobs
            else:
                kept = filter_jobs(raw_jobs)

            kept_dicts = [j.to_dict() for j in kept]
            stats = db.upsert_jobs(kept_dicts, search_location=loc, source="linkedin")
            per_location.append({
                "location": label,
                "scraped": len(raw_jobs),
                "matched": len(kept),
                **stats,
            })
            total_new += stats["new"]
            total_updated += stats["updated"]
            total_seen += stats["total_seen"]
            logger.info(
                "  %s — scraped=%d matched=%d new=%d updated=%d",
                label, len(raw_jobs), len(kept), stats["new"], stats["updated"],
            )

    except Exception as exc:
        logger.exception("Daily scrape failed: %s", exc)
        error = str(exc)

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "started_at": started_at,
        "finished_at": finished_at,
        "locations": [(loc or "(worldwide)") for loc in locations],
        "per_location": per_location,
        "new": total_new,
        "updated": total_updated,
        "seen": total_seen,
        "error": error,
    }
    db.record_run(summary)

    _set_state(
        running=False,
        progress=(
            f"Done — {total_new} new, {total_updated} updated across {len(locations)} location(s)."
            if not error else f"Error: {error}"
        ),
        current_location="",
        finished_at=finished_at,
        last_error=error,
        summary=summary,
    )
    logger.info(
        "=== Daily scrape finished — new=%d updated=%d seen=%d ===",
        total_new, total_updated, total_seen,
    )
    return summary


# ── Remote-jobs scrape ────────────────────────────────────────────────────

def run_remote_scrape_now(
    company_keys: list[str] | None = None,
    max_pages: int = 2,
    skip_details: bool = True,
    progress_cb: Callable[[str], None] | None = None,
) -> dict:
    """Scrape remote jobs across the saved companies. Single-flight (shared lock).

    Args:
        company_keys: optional list of `company.key` values to limit the run.
                      When None, scrapes every enabled company.
    """
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("A scrape is already running.")
    try:
        return _do_remote_run(company_keys, max_pages, skip_details, progress_cb)
    finally:
        _run_lock.release()


def _do_remote_run(
    company_keys: list[str] | None,
    max_pages: int,
    skip_details: bool,
    progress_cb: Callable[[str], None] | None,
) -> dict:
    all_companies = db.list_companies()
    by_key = {c.get("key"): c for c in all_companies}
    if company_keys:
        targets = [by_key[k] for k in company_keys if k in by_key]
    else:
        targets = [c for c in all_companies if c.get("enabled", True)]

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _set_state(
        running=True,
        kind="remote",
        progress=f"Starting remote scrape across {len(targets)} company/companies…",
        current_location="",
        current_company="",
        started_at=started_at,
        finished_at=None,
        last_error=None,
        summary=None,
    )
    logger.info("=== Remote scrape started — %d company/companies ===", len(targets))

    per_company: list[dict] = []
    total_new = 0
    total_updated = 0
    total_seen = 0
    error: str | None = None

    try:
        for idx, company in enumerate(targets, 1):
            name = company.get("name") or company.get("slug") or "(unknown)"
            slug = company.get("slug") or ""
            msg = f"[{idx}/{len(targets)}] Scraping remote jobs at {name}…"
            logger.info(msg)
            _set_state(progress=msg, current_company=name)
            if progress_cb:
                progress_cb(msg)

            scraper = RemoteJobScraper(
                company_name=name,
                company_slug=slug,
                max_pages=max_pages,
                skip_details=skip_details,
            )
            try:
                raw_jobs: list[Job] = scraper.scrape()
            finally:
                scraper.close()

            kept_dicts = [j.to_dict() for j in raw_jobs]
            stats = db.upsert_jobs(kept_dicts, search_location="remote", source="remote")
            per_company.append({
                "company": name,
                "scraped": len(raw_jobs),
                **stats,
            })
            total_new += stats["new"]
            total_updated += stats["updated"]
            total_seen += stats["total_seen"]
            logger.info(
                "  %s — scraped=%d new=%d updated=%d",
                name, len(raw_jobs), stats["new"], stats["updated"],
            )
    except Exception as exc:
        logger.exception("Remote scrape failed: %s", exc)
        error = str(exc)

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "kind": "remote",
        "started_at": started_at,
        "finished_at": finished_at,
        "companies": [c.get("name") for c in targets],
        "per_company": per_company,
        "new": total_new,
        "updated": total_updated,
        "seen": total_seen,
        "error": error,
    }
    db.record_run(summary)

    _set_state(
        running=False,
        progress=(
            f"Done — {total_new} new, {total_updated} updated across "
            f"{len(targets)} company/companies."
            if not error else f"Error: {error}"
        ),
        current_company="",
        finished_at=finished_at,
        last_error=error,
        summary=summary,
    )
    logger.info(
        "=== Remote scrape finished — new=%d updated=%d seen=%d ===",
        total_new, total_updated, total_seen,
    )
    return summary


# ── APScheduler wiring ────────────────────────────────────────────────────

def _scheduled_job():
    """Wrapper used by APScheduler — silently swallow concurrent-run errors."""
    try:
        run_scrape_now()
    except RuntimeError:
        logger.warning("Daily scrape skipped — another run is in progress.")
    except Exception:
        logger.exception("Daily scrape crashed.")


def start_scheduler() -> BackgroundScheduler | None:
    """Start (or reconfigure) the background scheduler. Idempotent.

    Returns None when DISABLE_SCHEDULER is set (Azure Container Apps Job
    handles the cron in that environment).
    """
    global _scheduler
    if _scheduler_disabled():
        logger.info("In-process scheduler disabled (DISABLE_SCHEDULER set).")
        return None
    settings = db.get_settings()
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True, timezone=_UTC)
        _scheduler.start()
        logger.info("Background scheduler started.")
    apply_schedule(settings)
    return _scheduler


def apply_schedule(settings: dict | None = None) -> dict:
    """(Re)install the daily cron job with the latest settings.

    Returns a small dict describing the next-run state.
    """
    global _scheduler
    if _scheduler_disabled():
        return {"enabled": False, "next_run": None, "managed_by": "azure"}
    if _scheduler is None:
        start_scheduler()
        return apply_schedule(settings)

    settings = settings or db.get_settings()
    enabled = bool(settings.get("schedule_enabled", True))
    hour = int(settings.get("schedule_hour", 6))
    minute = int(settings.get("schedule_minute", 0))

    # Remove old job if present.
    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)

    if not enabled:
        logger.info("Daily schedule disabled.")
        return {"enabled": False, "next_run": None, "hour": hour, "minute": minute}

    trigger = CronTrigger(hour=hour, minute=minute, timezone=_UTC)
    job = _scheduler.add_job(
        _scheduled_job,
        trigger=trigger,
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    next_run = job.next_run_time.isoformat() if job.next_run_time else None
    logger.info("Daily scrape scheduled at %02d:%02d UTC — next run: %s", hour, minute, next_run)
    return {"enabled": True, "next_run": next_run, "hour": hour, "minute": minute}


def get_schedule_info() -> dict:
    if _scheduler_disabled():
        settings = db.get_settings()
        return {
            "enabled": bool(settings.get("schedule_enabled", True)),
            "next_run": None,
            "hour": int(settings.get("schedule_hour", 6)),
            "minute": int(settings.get("schedule_minute", 0)),
            "managed_by": "azure",
        }
    if _scheduler is None:
        return {"enabled": False, "next_run": None}
    job = _scheduler.get_job(JOB_ID)
    settings = db.get_settings()
    return {
        "enabled": bool(settings.get("schedule_enabled", True)) and job is not None,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "hour": int(settings.get("schedule_hour", 6)),
        "minute": int(settings.get("schedule_minute", 0)),
    }


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
