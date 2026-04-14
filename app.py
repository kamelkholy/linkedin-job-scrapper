#!/usr/bin/env python3
"""
LinkedIn Job Scraper — Flask web server.

Serves the dashboard and exposes an API to trigger scrapes with custom parameters.
"""

import collections
import json
import logging
import os
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import config
from filters import export_csv, export_json, filter_jobs
from scraper import LinkedInScraper

app = Flask(__name__, static_folder="output")

# ── Log capture ─────────────────────────────────────────────────────────────
LOG_BUFFER_SIZE = 500
log_buffer: collections.deque = collections.deque(maxlen=LOG_BUFFER_SIZE)
log_lock = threading.Lock()


class BufferHandler(logging.Handler):
    """Captures log records into an in-memory ring buffer."""

    def emit(self, record):
        # Skip werkzeug request logs — they're noisy and not useful in the UI
        if record.name == "werkzeug":
            return
        entry = self.format(record)
        with log_lock:
            log_buffer.append(entry)


_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S")

# Console handler
_console = logging.StreamHandler()
_console.setFormatter(_fmt)

# Buffer handler (feeds the web UI)
_buffer_handler = BufferHandler()
_buffer_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console, _buffer_handler])
logger = logging.getLogger("app")

# ── Scrape state ────────────────────────────────────────────────────────────
scrape_state = {
    "running": False,
    "progress": "",
    "error": None,
    "job_count": 0,
    "filtered_count": 0,
}
scrape_lock = threading.Lock()


def _clear_logs():
    with log_lock:
        log_buffer.clear()


def _run_scrape(params: dict):
    """Execute a scrape in a background thread."""
    global scrape_state
    try:
        # Apply parameters
        config.SEARCH_KEYWORDS = params.get("keywords", config.SEARCH_KEYWORDS)
        config.LOCATION = params.get("location", config.LOCATION)
        config.GEO_ID = params.get("geoId", config.GEO_ID)
        config.MAX_PAGES = int(params.get("maxPages", config.MAX_PAGES))
        no_filter = params.get("noFilter", False)

        with scrape_lock:
            scrape_state["progress"] = "Initialising browser…"

        scraper = LinkedInScraper()
        try:
            with scrape_lock:
                scrape_state["progress"] = "Scraping job listings…"
            jobs = scraper.scrape()

            with scrape_lock:
                scrape_state["job_count"] = len(jobs)
                scrape_state["progress"] = f"Scraped {len(jobs)} jobs. Filtering…"

            if no_filter:
                filtered = jobs
            else:
                filtered = filter_jobs(jobs)

            with scrape_lock:
                scrape_state["filtered_count"] = len(filtered)
                scrape_state["progress"] = "Exporting results…"

            if filtered:
                export_csv(filtered)
                export_json(filtered)

            with scrape_lock:
                scrape_state["progress"] = f"Done — {len(filtered)} jobs exported."
                scrape_state["running"] = False

        finally:
            scraper.close()

    except Exception as exc:
        logger.exception("Scrape failed: %s", exc)
        with scrape_lock:
            scrape_state["error"] = str(exc)
            scrape_state["running"] = False
            scrape_state["progress"] = f"Error: {exc}"


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("output", "index.html")


@app.route("/output/<path:filename>")
def output_files(filename):
    return send_from_directory("output", filename)


@app.post("/api/scrape")
def start_scrape():
    global scrape_state
    with scrape_lock:
        if scrape_state["running"]:
            return jsonify({"ok": False, "error": "A scrape is already running."}), 409

    params = request.get_json(force=True, silent=True) or {}

    # Basic validation
    keywords = params.get("keywords", "").strip()
    if not keywords:
        return jsonify({"ok": False, "error": "Keywords are required."}), 400

    max_pages = params.get("maxPages", config.MAX_PAGES)
    try:
        max_pages = int(max_pages)
        if max_pages < 1 or max_pages > 50:
            raise ValueError
        params["maxPages"] = max_pages
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "maxPages must be 1–50."}), 400

    _clear_logs()

    with scrape_lock:
        scrape_state = {
            "running": True,
            "progress": "Starting…",
            "error": None,
            "job_count": 0,
            "filtered_count": 0,
        }

    thread = threading.Thread(target=_run_scrape, args=(params,), daemon=True)
    thread.start()

    return jsonify({"ok": True, "message": "Scrape started."})


@app.get("/api/status")
def scrape_status():
    with scrape_lock:
        state = dict(scrape_state)
    with log_lock:
        state["logs"] = list(log_buffer)
    return jsonify(state)


@app.get("/api/logs")
def get_logs():
    """Return captured log lines. ?since=N returns only lines after index N."""
    since = request.args.get("since", 0, type=int)
    with log_lock:
        all_logs = list(log_buffer)
    return jsonify({"logs": all_logs[since:], "total": len(all_logs)})


@app.get("/api/jobs")
def get_jobs():
    json_path = os.path.join(config.OUTPUT_DIR, config.OUTPUT_JSON)
    if not os.path.isfile(json_path):
        return jsonify([])
    with open(json_path, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.get("/api/config")
def get_config():
    return jsonify({
        "keywords": config.SEARCH_KEYWORDS,
        "location": config.LOCATION,
        "geoId": config.GEO_ID,
        "maxPages": config.MAX_PAGES,
    })


if __name__ == "__main__":
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    app.run(debug=True, port=5000)
