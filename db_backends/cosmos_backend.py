"""Azure Cosmos DB (NoSQL Core API) backend.

Authentication: prefers Managed Identity / DefaultAzureCredential, falls
back to a connection key from `COSMOS_KEY` for local dev.

Containers (created automatically if missing):
    jobs      partition key /source        (id = sha1(url))
    settings  partition key /id            (single doc id="settings")
    runs      partition key /yearMonth     (id = uuid)
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from azure.cosmos import CosmosClient, PartitionKey, exceptions

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _year_month(iso: str | None = None) -> str:
    if iso:
        try:
            d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except Exception:
            d = datetime.now(timezone.utc)
    else:
        d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m")


class CosmosBackend:
    name = "cosmos"

    def __init__(self, endpoint: str, database: str, key: str | None = None):
        if key:
            client = CosmosClient(endpoint, credential=key)
            logger.info("Cosmos connected with key auth at %s", endpoint)
        else:
            from azure.identity import DefaultAzureCredential
            cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
            client = CosmosClient(endpoint, credential=cred)
            logger.info("Cosmos connected with AAD/Managed Identity at %s", endpoint)

        # Database is provisioned by Bicep; we only verify it exists.
        self._db = client.get_database_client(database)
        try:
            self._db.read()
        except exceptions.CosmosResourceNotFoundError:
            # In dev, allow the backend to create the DB itself.
            client.create_database_if_not_exists(database)
            self._db = client.get_database_client(database)

        self._jobs = self._ensure_container("jobs", PartitionKey(path="/source"))
        self._settings = self._ensure_container("settings", PartitionKey(path="/id"))
        self._runs = self._ensure_container("runs", PartitionKey(path="/yearMonth"))

    def _ensure_container(self, name: str, pk: PartitionKey):
        try:
            return self._db.create_container_if_not_exists(id=name, partition_key=pk)
        except exceptions.CosmosHttpResponseError as exc:
            # In serverless mode the SDK call still works; this is a defensive log.
            logger.warning("Could not create container %s (continuing): %s", name, exc)
            return self._db.get_container_client(name)

    def close(self) -> None:  # Cosmos client uses HTTP; nothing to close
        pass

    # ── Jobs ─────────────────────────────────────────────────────────────

    def upsert_jobs(self, jobs: Iterable[dict], search_location: str, source: str) -> dict:
        new_count = 0
        updated_count = 0
        total = 0
        now = _utcnow()

        for raw in jobs:
            url = (raw.get("url") or "").strip()
            if not url:
                continue
            total += 1
            doc_id = _job_id(url)
            try:
                existing = self._jobs.read_item(item=doc_id, partition_key=source)
            except exceptions.CosmosResourceNotFoundError:
                existing = None

            if existing is None:
                doc = {
                    "id": doc_id,
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
                self._jobs.create_item(body=doc)
                new_count += 1
            else:
                locs = list(existing.get("search_locations") or [])
                if search_location and search_location not in locs:
                    locs.append(search_location)
                existing["last_seen"] = now
                existing["search_locations"] = locs
                if raw.get("description") and not existing.get("description"):
                    existing["description"] = raw["description"]
                if raw.get("relocation_mentions") and not existing.get("relocation_mentions"):
                    existing["relocation_mentions"] = raw["relocation_mentions"]
                if raw.get("posted_date") and not existing.get("posted_date"):
                    existing["posted_date"] = raw["posted_date"]
                self._jobs.replace_item(item=doc_id, body=existing)
                updated_count += 1

        return {"new": new_count, "updated": updated_count, "total_seen": total}

    def list_jobs(self, status, search, location, limit) -> list[dict]:
        clauses: list[str] = []
        params: list[dict] = []

        if status:
            if status == "active":
                clauses.append("c.status NOT IN ('dismissed','archived')")
            else:
                clauses.append("c.status = @status")
                params.append({"name": "@status", "value": status})
        if search:
            clauses.append(
                "(CONTAINS(LOWER(c.title), @s) OR CONTAINS(LOWER(c.company), @s) OR CONTAINS(LOWER(c.location), @s))"
            )
            params.append({"name": "@s", "value": search.lower()})
        if location:
            clauses.append("CONTAINS(LOWER(c.location), @loc)")
            params.append({"name": "@loc", "value": location.lower()})

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        top_clause = f"TOP {int(limit)}" if limit else ""
        query = f"SELECT {top_clause} * FROM c {where} ORDER BY c.last_seen DESC"
        items = list(
            self._jobs.query_items(query=query, parameters=params, enable_cross_partition_query=True)
        )
        return items

    def get_job(self, url: str) -> dict | None:
        doc_id = _job_id(url)
        # We don't know the partition (source) up front, so do a query.
        items = list(self._jobs.query_items(
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": doc_id}],
            enable_cross_partition_query=True,
        ))
        return items[0] if items else None

    def update_job_status(self, url: str, status: str, applied_at, dismissed_at, notes) -> bool:
        existing = self.get_job(url)
        if not existing:
            return False
        existing["status"] = status
        if applied_at is not None:
            existing["applied_at"] = applied_at
        if dismissed_at is not None:
            existing["dismissed_at"] = dismissed_at
        if notes is not None:
            existing["notes"] = notes
        self._jobs.replace_item(item=existing["id"], body=existing)
        return True

    def update_job_notes(self, url: str, notes: str) -> bool:
        existing = self.get_job(url)
        if not existing:
            return False
        existing["notes"] = notes
        self._jobs.replace_item(item=existing["id"], body=existing)
        return True

    def delete_job(self, url: str) -> bool:
        existing = self.get_job(url)
        if not existing:
            return False
        self._jobs.delete_item(item=existing["id"], partition_key=existing.get("source", "linkedin"))
        return True

    def stats(self) -> dict:
        # Single aggregate query keeps RU usage low.
        items = list(self._jobs.query_items(
            query="SELECT c.status, c.company, c.location FROM c",
            enable_cross_partition_query=True,
        ))
        by_status: dict[str, int] = {}
        companies: set[str] = set()
        locations: set[str] = set()
        for d in items:
            s = d.get("status", "new")
            by_status[s] = by_status.get(s, 0) + 1
            if d.get("company"):
                companies.add(d["company"])
            if d.get("location"):
                locations.add(d["location"])
        return {"total": len(items), "by_status": by_status, "companies": len(companies), "locations": len(locations)}

    # ── Settings ─────────────────────────────────────────────────────────

    def get_settings(self) -> dict | None:
        try:
            return self._settings.read_item(item="settings", partition_key="settings")
        except exceptions.CosmosResourceNotFoundError:
            return None

    def upsert_settings(self, doc: dict) -> dict:
        doc = dict(doc)
        doc["id"] = "settings"
        self._settings.upsert_item(body=doc)
        return doc

    # ── Runs ─────────────────────────────────────────────────────────────

    def insert_run(self, summary: dict) -> int:
        doc = dict(summary)
        doc["id"] = uuid.uuid4().hex
        doc["yearMonth"] = _year_month(doc.get("started_at"))
        self._runs.create_item(body=doc)
        return 1

    def list_runs(self, limit: int) -> list[dict]:
        items = list(self._runs.query_items(
            query=f"SELECT TOP {int(limit)} * FROM c ORDER BY c.started_at DESC",
            enable_cross_partition_query=True,
        ))
        return items

    # ── Migration helpers ───────────────────────────────────────────────

    def jobs_count(self) -> int:
        items = list(self._jobs.query_items(
            query="SELECT VALUE COUNT(1) FROM c",
            enable_cross_partition_query=True,
        ))
        return int(items[0]) if items else 0
