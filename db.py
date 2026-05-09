"""Persistence facade — selects a backend at startup.

Backend selection (env vars):
    COSMOS_ENDPOINT  → use Azure Cosmos DB
    (otherwise)      → use the local TinyDB file

The public API is what `app.py` and `scheduler.py` consume. Adding new
backends only requires implementing the methods used here.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

import config

logger = logging.getLogger(__name__)

_backend = None
_init_lock = threading.Lock()

VALID_STATUSES = {"new", "applied", "dismissed", "archived"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(path: str | None = None):
    """Initialise the backend chosen by env vars. Idempotent."""
    global _backend
    if _backend is not None:
        return _backend

    with _init_lock:
        if _backend is not None:
            return _backend

        cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT", "").strip()
        if cosmos_endpoint:
            from db_backends.cosmos_backend import CosmosBackend
            _backend = CosmosBackend(
                endpoint=cosmos_endpoint,
                database=os.environ.get("COSMOS_DB", "linkedinscraper"),
                key=os.environ.get("COSMOS_KEY") or None,
            )
        else:
            from db_backends.tinydb_backend import TinyDBBackend
            _backend = TinyDBBackend(path or config.DB_PATH)

        logger.info("Database backend: %s", _backend.name)
        return _backend


def close_db() -> None:
    global _backend
    if _backend is not None:
        _backend.close()
        _backend = None


def _b():
    if _backend is None:
        init_db()
    return _backend


# ── Jobs ──────────────────────────────────────────────────────────────────

def upsert_jobs(jobs: Iterable[dict], search_location: str = "", source: str = "linkedin") -> dict:
    return _b().upsert_jobs(jobs, search_location=search_location, source=source)


def list_jobs(status: str | None = None, search: str | None = None,
              location: str | None = None, limit: int | None = None) -> list[dict]:
    return _b().list_jobs(status, search, location, limit)


def get_job(url: str) -> dict | None:
    return _b().get_job(url)


def update_job_status(url: str, status: str, notes: str | None = None) -> bool:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    now = _utcnow()
    applied_at = now if status == "applied" else None
    dismissed_at = now if status == "dismissed" else None
    return _b().update_job_status(url, status, applied_at, dismissed_at, notes)


def update_job_notes(url: str, notes: str) -> bool:
    return _b().update_job_notes(url, notes)


def delete_job(url: str) -> bool:
    return _b().delete_job(url)


def stats() -> dict:
    return _b().stats()


# ── Settings ──────────────────────────────────────────────────────────────

DEFAULT_SETTINGS: dict[str, Any] = {
    "id": "settings",
    "keywords": "",
    "locations": [],
    "geo_id": "",
    "max_pages": 10,
    "skip_details": False,
    "no_filter": False,
    "schedule_hour": 6,
    "schedule_minute": 0,
    "schedule_enabled": True,
}


def get_settings() -> dict:
    doc = _b().get_settings()
    if doc is None:
        seed = dict(DEFAULT_SETTINGS)
        seed["keywords"] = config.SEARCH_KEYWORDS
        seed["locations"] = list(config.LOCATIONS) if config.LOCATIONS else (
            [config.LOCATION] if config.LOCATION else []
        )
        seed["geo_id"] = config.GEO_ID
        seed["max_pages"] = config.MAX_PAGES
        seed["skip_details"] = config.SKIP_DETAILS
        seed["schedule_hour"] = config.SCHEDULE_HOUR
        seed["schedule_minute"] = config.SCHEDULE_MINUTE
        _b().upsert_settings(seed)
        return seed
    merged = dict(DEFAULT_SETTINGS)
    merged.update(doc)
    return merged


def update_settings(patch: dict) -> dict:
    current = get_settings()
    allowed = set(DEFAULT_SETTINGS.keys()) - {"id"}
    cleaned = {k: v for k, v in patch.items() if k in allowed}
    if "schedule_hour" in cleaned:
        cleaned["schedule_hour"] = max(0, min(23, int(cleaned["schedule_hour"])))
    if "schedule_minute" in cleaned:
        cleaned["schedule_minute"] = max(0, min(59, int(cleaned["schedule_minute"])))
    if "max_pages" in cleaned:
        cleaned["max_pages"] = max(1, min(50, int(cleaned["max_pages"])))
    if "locations" in cleaned and isinstance(cleaned["locations"], list):
        cleaned["locations"] = [str(s).strip() for s in cleaned["locations"] if str(s).strip()]
    current.update(cleaned)
    _b().upsert_settings(current)
    return current


# ── Runs ──────────────────────────────────────────────────────────────────

def record_run(summary: dict) -> int:
    summary = dict(summary)
    summary.setdefault("started_at", _utcnow())
    summary.setdefault("finished_at", _utcnow())
    return _b().insert_run(summary)


def list_runs(limit: int = 20) -> list[dict]:
    return _b().list_runs(limit)


# ── One-shot legacy import ────────────────────────────────────────────────

def migrate_legacy_json(json_path: str) -> int:
    if not os.path.isfile(json_path):
        return 0
    if _b().jobs_count() > 0:
        return 0
    try:
        with open(json_path, encoding="utf-8") as f:
            legacy = json.load(f)
    except Exception as exc:
        logger.warning("Could not read legacy JSON %s: %s", json_path, exc)
        return 0
    if not isinstance(legacy, list):
        return 0
    s = upsert_jobs(legacy, search_location="", source="linkedin")
    logger.info("Migrated %d legacy jobs into the DB.", s["new"])
    return s["new"]
