"""TinyDB-backed implementation (default for local development).

Public methods mirror the names used by `db.py`. The cosmos backend
implements the same surface so they're swappable.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from tinydb import Query, TinyDB
from tinydb.middlewares import CachingMiddleware
from tinydb.storages import JSONStorage

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TinyDBBackend:
    """File-based JSON store. Single-process; protected by an in-process lock."""

    name = "tinydb"

    def __init__(self, path: str):
        self._path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._db = TinyDB(path, storage=CachingMiddleware(JSONStorage), indent=2, ensure_ascii=False)
        logger.info("TinyDB opened at %s", path)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _flush(self) -> None:
        try:
            self._db.storage.flush()  # type: ignore[attr-defined]
        except Exception:
            pass

    # ── Jobs ─────────────────────────────────────────────────────────────

    def upsert_jobs(self, jobs: Iterable[dict], search_location: str, source: str) -> dict:
        Job = Query()
        new_count = 0
        updated_count = 0
        total = 0
        now = _utcnow()
        table = self._db.table("jobs")

        with self._lock:
            for raw in jobs:
                url = (raw.get("url") or "").strip()
                if not url:
                    continue
                total += 1
                existing = table.get(Job.url == url)
                if existing is None:
                    doc = {
                        "url": url,
                        "title": raw.get("title", ""),
                        "company": raw.get("company", ""),
                        "location": raw.get("location", ""),
                        "description": raw.get("description", ""),
                        "posted_date": raw.get("posted_date", ""),
                        "relocation_mentions": raw.get("relocation_mentions", ""),
                        "source": source,
                        "search_locations": [search_location] if search_location else [],
                        "status": "new",
                        "first_seen": now,
                        "last_seen": now,
                        "applied_at": None,
                        "dismissed_at": None,
                        "notes": "",
                    }
                    table.insert(doc)
                    new_count += 1
                else:
                    locs = list(existing.get("search_locations") or [])
                    if search_location and search_location not in locs:
                        locs.append(search_location)
                    patch: dict[str, Any] = {"last_seen": now, "search_locations": locs}
                    if raw.get("description") and not existing.get("description"):
                        patch["description"] = raw["description"]
                    if raw.get("relocation_mentions") and not existing.get("relocation_mentions"):
                        patch["relocation_mentions"] = raw["relocation_mentions"]
                    if raw.get("posted_date") and not existing.get("posted_date"):
                        patch["posted_date"] = raw["posted_date"]
                    table.update(patch, Job.url == url)
                    updated_count += 1
            self._flush()

        return {"new": new_count, "updated": updated_count, "total_seen": total}

    def list_jobs(self, status, search, location, limit, source=None) -> list[dict]:
        with self._lock:
            docs = self._db.table("jobs").all()

        if source:
            docs = [d for d in docs if (d.get("source") or "linkedin") == source]
        if status:
            if status == "active":
                docs = [d for d in docs if d.get("status") not in ("dismissed", "archived")]
            else:
                docs = [d for d in docs if d.get("status") == status]
        if search:
            s = search.lower()
            docs = [
                d for d in docs
                if s in (d.get("title", "") + " " + d.get("company", "") + " " + d.get("location", "")).lower()
            ]
        if location:
            loc_low = location.lower()
            docs = [
                d for d in docs
                if loc_low in (d.get("location", "") or "").lower()
                or any(loc_low in (sl or "").lower() for sl in d.get("search_locations", []))
            ]
        docs.sort(key=lambda d: d.get("last_seen", ""), reverse=True)
        if limit:
            docs = docs[:limit]
        return docs

    def get_job(self, url: str) -> dict | None:
        Job = Query()
        with self._lock:
            return self._db.table("jobs").get(Job.url == url)

    def update_job_status(self, url: str, status: str, applied_at: str | None, dismissed_at: str | None, notes: str | None) -> bool:
        Job = Query()
        patch: dict[str, Any] = {"status": status}
        if applied_at is not None:
            patch["applied_at"] = applied_at
        if dismissed_at is not None:
            patch["dismissed_at"] = dismissed_at
        if notes is not None:
            patch["notes"] = notes
        with self._lock:
            res = self._db.table("jobs").update(patch, Job.url == url)
            self._flush()
        return bool(res)

    def update_job_notes(self, url: str, notes: str) -> bool:
        Job = Query()
        with self._lock:
            res = self._db.table("jobs").update({"notes": notes}, Job.url == url)
            self._flush()
        return bool(res)

    def delete_job(self, url: str) -> bool:
        Job = Query()
        with self._lock:
            removed = self._db.table("jobs").remove(Job.url == url)
            self._flush()
        return bool(removed)

    def stats(self, source=None) -> dict:
        with self._lock:
            docs = self._db.table("jobs").all()
        if source:
            docs = [d for d in docs if (d.get("source") or "linkedin") == source]
        by_status: dict[str, int] = {}
        companies: set[str] = set()
        locations: set[str] = set()
        for d in docs:
            s = d.get("status", "new")
            by_status[s] = by_status.get(s, 0) + 1
            if d.get("company"):
                companies.add(d["company"])
            if d.get("location"):
                locations.add(d["location"])
        return {"total": len(docs), "by_status": by_status, "companies": len(companies), "locations": len(locations)}

    # ── Settings ─────────────────────────────────────────────────────────

    def get_settings(self) -> dict | None:
        Settings = Query()
        with self._lock:
            return self._db.table("settings").get(Settings.id == "settings")

    def upsert_settings(self, doc: dict) -> dict:
        Settings = Query()
        with self._lock:
            self._db.table("settings").upsert(doc, Settings.id == "settings")
            self._flush()
        return doc

    # ── Runs ─────────────────────────────────────────────────────────────

    def insert_run(self, summary: dict) -> int:
        with self._lock:
            doc_id = self._db.table("runs").insert(summary)
            self._flush()
        return int(doc_id)

    def list_runs(self, limit: int) -> list[dict]:
        with self._lock:
            docs = list(self._db.table("runs").all())
        docs.sort(key=lambda d: d.get("started_at", ""), reverse=True)
        return docs[:limit]

    # ── Migration helpers ───────────────────────────────────────────────

    def jobs_count(self) -> int:
        with self._lock:
            return len(self._db.table("jobs"))

    # ── Companies (for remote-jobs feature) ─────────────────────────────

    def list_companies(self) -> list[dict]:
        with self._lock:
            docs = list(self._db.table("companies").all())
        docs.sort(key=lambda d: (d.get("name") or "").lower())
        return docs

    def add_company(self, doc: dict) -> dict:
        Company = Query()
        key = (doc.get("slug") or doc.get("name") or "").strip().lower()
        if not key:
            raise ValueError("company name is required")
        with self._lock:
            existing = self._db.table("companies").get(Company.key == key)
            if existing:
                merged = dict(existing)
                merged.update({k: v for k, v in doc.items() if v not in (None, "")})
                self._db.table("companies").update(merged, Company.key == key)
                self._flush()
                return merged
            doc = dict(doc)
            doc["key"] = key
            doc.setdefault("enabled", True)
            doc.setdefault("added_at", _utcnow())
            self._db.table("companies").insert(doc)
            self._flush()
            return doc

    def update_company(self, key: str, patch: dict) -> dict | None:
        Company = Query()
        with self._lock:
            existing = self._db.table("companies").get(Company.key == key)
            if not existing:
                return None
            merged = dict(existing)
            merged.update(patch)
            self._db.table("companies").update(merged, Company.key == key)
            self._flush()
            return merged

    def remove_company(self, key: str) -> bool:
        Company = Query()
        with self._lock:
            removed = self._db.table("companies").remove(Company.key == key)
            self._flush()
        return bool(removed)

    def companies_count(self) -> int:
        with self._lock:
            return len(self._db.table("companies"))
