#!/usr/bin/env python3
"""LinkedIn Job Scraper — Flask web server.

- Serves the dashboard.
- Persists jobs and runtime settings in TinyDB (NoSQL).
- Runs a daily background scrape across multiple locations.
- Exposes APIs to manage jobs (apply / dismiss / archive / notes) and to
  edit settings (locations, schedule, keywords).
"""

from __future__ import annotations

import collections
import hmac
import logging
import os
import threading
from base64 import b64decode
from binascii import Error as BinasciiError

from flask import Flask, Response, jsonify, request, send_from_directory

import config
import db
import scheduler as sched
from filters import export_csv, export_json
from scraper import Job

app = Flask(__name__, static_folder="output")

# ── Auth ──────────────────────────────────────────────────────────────────
# HTTP Basic Auth gated on AUTH_USERNAME / AUTH_PASSWORD env vars.
# If either is empty, auth is disabled (local dev).
_AUTH_USER = os.environ.get("AUTH_USERNAME", "").strip()
_AUTH_PASS = os.environ.get("AUTH_PASSWORD", "")
_AUTH_REALM = os.environ.get("AUTH_REALM", "LinkedIn Scraper")
_AUTH_ENABLED = bool(_AUTH_USER and _AUTH_PASS)


def _credentials_match(supplied_user: str, supplied_pass: str) -> bool:
    # Constant-time compare on both fields to avoid timing oracles.
    user_ok = hmac.compare_digest(supplied_user.encode("utf-8"), _AUTH_USER.encode("utf-8"))
    pass_ok = hmac.compare_digest(supplied_pass.encode("utf-8"), _AUTH_PASS.encode("utf-8"))
    return user_ok and pass_ok


def _unauthorized() -> Response:
    resp = Response("Authentication required.", status=401, mimetype="text/plain")
    resp.headers["WWW-Authenticate"] = f'Basic realm="{_AUTH_REALM}", charset="UTF-8"'
    return resp


@app.before_request
def _require_basic_auth():
    if not _AUTH_ENABLED:
        return None
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return _unauthorized()
    try:
        decoded = b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (BinasciiError, UnicodeDecodeError):
        return _unauthorized()
    user, sep, password = decoded.partition(":")
    if not sep or not _credentials_match(user, password):
        return _unauthorized()
    return None

# ── Log capture ─────────────────────────────────────────────────────────────
LOG_BUFFER_SIZE = 500
log_buffer: collections.deque = collections.deque(maxlen=LOG_BUFFER_SIZE)
log_lock = threading.Lock()


class BufferHandler(logging.Handler):
    """Captures log records into an in-memory ring buffer."""

    def emit(self, record):
        if record.name == "werkzeug":
            return
        entry = self.format(record)
        with log_lock:
            log_buffer.append(entry)


_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S")
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
_buffer_handler = BufferHandler()
_buffer_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console, _buffer_handler])

# Silence chatty Azure SDK loggers (Cosmos HTTP request/response dumps).
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

logger = logging.getLogger("app")


def _clear_logs():
    with log_lock:
        log_buffer.clear()


# ── Routes: pages & static ─────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/output/<path:filename>")
def output_files(filename):
    return send_from_directory("output", filename)


# ── Routes: jobs (DB-backed) ───────────────────────────────────────────────

@app.get("/api/jobs")
def get_jobs():
    """Return jobs from the database.

    Query params:
        status   — "active" (default) | "new" | "applied" | "dismissed" | "archived" | "all"
        search   — substring match on title/company/location
        location — substring match on location or search_locations
        limit    — int
    """
    status = request.args.get("status", "active")
    if status == "all":
        status = None
    search = request.args.get("search") or None
    location = request.args.get("location") or None
    limit = request.args.get("limit", type=int)
    return jsonify(db.list_jobs(status=status, search=search, location=location, limit=limit))


@app.get("/api/jobs/stats")
def get_jobs_stats():
    return jsonify(db.stats())


@app.post("/api/jobs/status")
def set_job_status():
    """Body: { "url": "...", "status": "applied|dismissed|archived|new", "notes": "..." (optional) }"""
    body = request.get_json(force=True, silent=True) or {}
    url = (body.get("url") or "").strip()
    status = (body.get("status") or "").strip()
    if not url or not status:
        return jsonify({"ok": False, "error": "url and status are required"}), 400
    try:
        ok = db.update_job_status(url, status, notes=body.get("notes"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if not ok:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True, "job": db.get_job(url)})


@app.post("/api/jobs/notes")
def set_job_notes():
    body = request.get_json(force=True, silent=True) or {}
    url = (body.get("url") or "").strip()
    notes = body.get("notes", "")
    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    ok = db.update_job_notes(url, notes)
    if not ok:
        return jsonify({"ok": False, "error": "job not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/jobs/delete")
def delete_job_route():
    body = request.get_json(force=True, silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "url is required"}), 400
    ok = db.delete_job(url)
    return jsonify({"ok": ok})


@app.post("/api/jobs/export")
def export_jobs():
    """Re-export the current DB contents to CSV + JSON files."""
    docs = db.list_jobs(status="active")
    jobs = [
        Job(
            title=d.get("title", ""),
            company=d.get("company", ""),
            location=d.get("location", ""),
            url=d.get("url", ""),
            description=d.get("description", ""),
            posted_date=d.get("posted_date", ""),
            relocation_mentions=(d.get("relocation_mentions") or "").split("; ")
                if d.get("relocation_mentions") else [],
        )
        for d in docs
    ]
    if jobs:
        export_csv(jobs)
        export_json(jobs)
    return jsonify({"ok": True, "exported": len(jobs)})


# ── Routes: settings ───────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    return jsonify(db.get_settings())


@app.post("/api/settings")
def update_settings():
    body = request.get_json(force=True, silent=True) or {}
    updated = db.update_settings(body)
    if any(k in body for k in ("schedule_hour", "schedule_minute", "schedule_enabled")):
        sched.apply_schedule(updated)
    return jsonify({"ok": True, "settings": updated, "schedule": sched.get_schedule_info()})


# Backwards-compat alias used by the original UI.
@app.get("/api/config")
def get_config():
    s = db.get_settings()
    return jsonify({
        "keywords": s.get("keywords", ""),
        "location": (s.get("locations") or [""])[0] if s.get("locations") else "",
        "geoId": s.get("geo_id", ""),
        "maxPages": s.get("max_pages", 10),
    })


# ── Routes: scheduler / scrape ─────────────────────────────────────────────

@app.get("/api/schedule")
def schedule_info():
    return jsonify(sched.get_schedule_info())


@app.get("/api/runs")
def list_runs():
    limit = request.args.get("limit", default=20, type=int)
    return jsonify(db.list_runs(limit=limit))


@app.post("/api/scrape")
def start_scrape():
    """Trigger an ad-hoc scrape (uses the same multi-location run as the daily job).

    Body (all optional — falls through to saved settings when omitted):
        { "keywords", "locations": [str], "geoId", "maxPages", "skipDetails", "noFilter" }
    """
    if sched.get_state().get("running"):
        return jsonify({"ok": False, "error": "A scrape is already running."}), 409

    body = request.get_json(force=True, silent=True) or {}

    # Map legacy single-location field if present.
    if "location" in body and "locations" not in body:
        body["locations"] = [body["location"]] if body["location"] else []

    # Persist any provided overrides into the settings doc, so the UI
    # stays consistent and the next daily run uses the same values.
    patch = {}
    if "keywords" in body and body["keywords"]:
        patch["keywords"] = body["keywords"].strip()
    if "locations" in body and isinstance(body["locations"], list):
        patch["locations"] = body["locations"]
    if "geoId" in body:
        patch["geo_id"] = body["geoId"]
    if "maxPages" in body:
        try:
            mp = int(body["maxPages"])
            if not (1 <= mp <= 50):
                raise ValueError
            patch["max_pages"] = mp
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "maxPages must be 1–50."}), 400
    if "skipDetails" in body:
        patch["skip_details"] = bool(body["skipDetails"])
    if "noFilter" in body:
        patch["no_filter"] = bool(body["noFilter"])
    if patch:
        db.update_settings(patch)

    settings = db.get_settings()
    if not (settings.get("keywords") or "").strip():
        return jsonify({"ok": False, "error": "Keywords are required."}), 400
    if not settings.get("locations"):
        return jsonify({"ok": False, "error": "At least one location is required."}), 400

    _clear_logs()
    thread = threading.Thread(target=sched._scheduled_job, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Scrape started."})


@app.get("/api/status")
def scrape_status():
    state = sched.get_state()
    state["schedule"] = sched.get_schedule_info()
    with log_lock:
        state["logs"] = list(log_buffer)
    return jsonify(state)


@app.get("/api/logs")
def get_logs():
    since = request.args.get("since", 0, type=int)
    with log_lock:
        all_logs = list(log_buffer)
    return jsonify({"logs": all_logs[since:], "total": len(all_logs)})


# ── Bootstrap ──────────────────────────────────────────────────────────────

def _bootstrap() -> None:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    db.init_db()
    db.get_settings()  # seeds defaults if missing
    legacy_path = os.path.join(config.OUTPUT_DIR, config.OUTPUT_JSON)
    db.migrate_legacy_json(legacy_path)
    sched.start_scheduler()


_bootstrap()


if __name__ == "__main__":
    # Disable the reloader — APScheduler does not survive Flask's double-import.
    app.run(debug=True, port=5000, use_reloader=False)
