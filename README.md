# LinkedIn Job Scraper — Senior SWE + Relocation

Scrapes LinkedIn's public job search for **senior software engineering** positions that mention **relocation support**, visa sponsorship, or similar benefits.

The Flask web server runs a **daily background job** that scrapes a configurable list of locations, deduplicates jobs across runs, and stores everything in a **TinyDB** NoSQL database. You manage the saved jobs (apply / dismiss / archive / notes), the search settings, and the daily schedule directly from the web dashboard.

---

## How It Works

1. **Daily background job** (APScheduler) runs at the time you choose, rotating through every location in your settings list.
2. For each location, **Selenium** opens LinkedIn's public job search pages (no login required), extracts cards, fetches descriptions, and applies the title/relocation filter.
3. Matching jobs are **upserted** into a TinyDB document store, keyed by URL — re-scraping the same job updates `last_seen` and adds the location to its `search_locations` list, so a job is never duplicated.
4. New jobs are flagged ✨ in the UI; jobs you dismiss / mark as applied / archive update status in the DB and persist across browsers.
5. Optional `output/linkedin_jobs.csv` + `output/linkedin_jobs.json` exports are still available on demand.

---

## Prerequisites

- **Python 3.10+**
- **Google Chrome** (Selenium 4.6+ handles ChromeDriver automatically)

---

## Setup

```bash
# 1. Clone/navigate to the project directory
cd "LinkedIn Scrapper"

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
venv\Scripts\activate          # Windows (PowerShell / CMD)
# source venv/bin/activate     # macOS / Linux

# 4. Install dependencies
pip install -r requirements.txt
```

---

## Running the Web Server (recommended)

```bash
python app.py
```

Then open **http://localhost:5000**. On first launch the server:

- Creates the database file at `output/jobs_db.json`
- Seeds default settings from `config.py` (keywords, locations, schedule)
- Migrates any pre-existing `output/linkedin_jobs.json` into the DB
- Starts the **APScheduler** background scheduler — the daily scrape will fire at the configured time (default `06:00 UTC`)

The dashboard shows a banner with the scheduler state and the next scheduled run. Open **Settings & Scrape** to:

- Edit **search keywords**
- Add / remove **locations** (the daily job rotates through every entry)
- Set the **daily schedule** (hour / minute, UTC) or disable it
- Tune `max pages per location`, skip-details, skip-filtering
- Save settings without running, or **Run Scrape Now** for an immediate multi-location run

### Job management (server-side, persisted in TinyDB)

- ☐ **Mark Applied** — toggles `status: "applied"` and stamps `applied_at`
- ✕ **Dismiss** — sets `status: "dismissed"` (with an undo bar to restore)
- The **Active jobs / All / New / Applied / Dismissed / Archived** filter swaps the DB query

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET`  | `/`                       | Serves the dashboard |
| `GET`  | `/api/jobs?status=&search=&location=&limit=` | List jobs from the DB |
| `GET`  | `/api/jobs/stats`         | Counts: total, by_status, companies, locations |
| `POST` | `/api/jobs/status`        | Body: `{url, status, notes?}` — set `new`/`applied`/`dismissed`/`archived` |
| `POST` | `/api/jobs/notes`         | Body: `{url, notes}` |
| `POST` | `/api/jobs/delete`        | Body: `{url}` — hard delete |
| `POST` | `/api/jobs/export`        | Re-export current DB to `output/linkedin_jobs.csv` + `.json` |
| `GET`  | `/api/settings`           | Read runtime settings |
| `POST` | `/api/settings`           | Update settings (any subset of fields) |
| `GET`  | `/api/schedule`           | `{enabled, next_run, hour, minute}` |
| `GET`  | `/api/runs?limit=20`      | Past background-run summaries |
| `POST` | `/api/scrape`             | Trigger an immediate multi-location scrape |
| `GET`  | `/api/status`             | Live progress, current location, recent logs |
| `GET`  | `/api/logs?since=N`       | Captured log lines since index N |

---

## Running the CLI (one-off, no server)

The original CLI still works for ad-hoc single-location runs that export to CSV/JSON only (it does **not** write to the DB):

```bash
python main.py --location "Ireland" --pages 10
python main.py --keywords "senior backend engineer relocation"
python main.py --no-filter --skip-details
```

| Flag | Description | Default |
|---|---|---|
| `-v`, `--verbose` | Enable debug-level logging | Off |
| `--keywords TEXT` | Override search keywords | from `config.py` |
| `--location TEXT` | Override search location | Worldwide |
| `--pages N` | Max listing pages to scrape (25 jobs/page) | `10` |
| `--no-filter` | Export all scraped jobs without filtering | Off |
| `--skip-details` | Skip fetching full job details/descriptions | Off |
| `--headed` | Show the browser window | Headless |

---

## Configuration

Default values live in [`config.py`](config.py); they are used to **seed** the DB on first launch. After that, edit settings from the web UI — those values live in the `settings` table of the TinyDB file and are what the daily job reads.

### Initial defaults

| Setting (`config.py`) | Description | Default |
|---|---|---|
| `SEARCH_KEYWORDS` | LinkedIn search query | `"senior software engineer relocation"` |
| `LOCATIONS` | List of locations rotated by the daily job | `["Ireland", "United Kingdom", "Germany", "Netherlands", "European Union"]` |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | Daily run time (UTC) | `06:00` |
| `DB_PATH` | TinyDB file path | `"output/jobs_db.json"` |
| `MAX_PAGES` | Pages per location | `10` |
| `HEADLESS_BROWSER` | Run Chrome headless | `True` |
| `REQUEST_DELAY` | Random delay range (seconds) | `(1, 3)` |

### Title & relocation keywords

`TITLE_KEYWORDS`, `RELOCATION_KEYWORDS`, and `RELOCATION_NEGATIVE_KEYWORDS` in `config.py` are still authoritative — they're consumed at filter-time and not stored in the DB. Edit `config.py` and restart to change them.

---

## Project Structure

```
LinkedIn Scrapper/
├── main.py              # CLI entry point (no DB)
├── app.py               # Flask server, API, bootstraps DB + scheduler
├── scheduler.py         # APScheduler daily job + multi-location runner
├── db.py                # TinyDB repository (jobs, settings, runs)
├── scraper.py           # Selenium-based LinkedIn scraper
├── filters.py           # Title/relocation filtering + CSV/JSON export
├── config.py            # Default settings (seed values)
├── index.html           # Web dashboard
├── requirements.txt     # Python dependencies (incl. tinydb, apscheduler)
├── .gitignore
├── README.md
└── output/
    ├── jobs_db.json         # ← TinyDB NoSQL database (jobs / settings / runs)
    ├── linkedin_jobs.csv    # Optional export
    └── linkedin_jobs.json   # Optional export
```

---

## Disclaimer

This tool is for **personal, educational use only**. Scraping LinkedIn may violate their [Terms of Service](https://www.linkedin.com/legal/user-agreement). Use responsibly:

- Keep request rates low (the default delay between requests is intentional)
- Don't use this for mass data collection or commercial purposes
- Consider using LinkedIn's official [Job Search API](https://learn.microsoft.com/en-us/linkedin/) if available
