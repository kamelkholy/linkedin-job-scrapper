# LinkedIn Job Scraper — Senior SWE + Relocation

Scrapes LinkedIn's public job search for **senior software engineering** positions that mention **relocation support**, visa sponsorship, or similar benefits. Results are exported to CSV/JSON and can be viewed in an interactive web dashboard.

---

## How It Works

1. **Selenium** opens LinkedIn's public job search pages (no login required)
2. Scrolls through listing pages and extracts job cards (title, company, location, URL)
3. Pre-filters by job title to skip irrelevant listings
4. Visits each matching job's detail page to extract the full description
5. Filters for jobs that mention relocation/visa keywords in the description
6. Deduplicates results by URL
7. Exports matches to `output/linkedin_jobs.csv` and `output/linkedin_jobs.json`
8. Results can be viewed in the built-in web dashboard (`output/index.html`)

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

## Running the Scraper

### Basic usage (worldwide search, default settings)

```bash
python main.py
```

### Search a specific location

```bash
python main.py --location "Ireland"
python main.py --location "United Kingdom"
python main.py --location "Germany"
```

### Custom search keywords

```bash
python main.py --keywords "senior backend engineer relocation visa"
```

### Control how many pages to scrape (25 jobs per page)

```bash
python main.py --pages 20
```

### Combine multiple options

```bash
python main.py --location "Ireland" --pages 25 --headed -v
```

### Export all jobs without filtering

```bash
python main.py --no-filter
```

### CLI Options Reference

| Flag | Description | Default |
|---|---|---|
| `-v`, `--verbose` | Enable debug-level logging | Off |
| `--keywords TEXT` | Override search keywords | `"senior software engineer relocation"` |
| `--location TEXT` | Override search location | Worldwide |
| `--pages N` | Max listing pages to scrape (25 jobs/page) | `10` |
| `--no-filter` | Export all scraped jobs without title/relocation filtering | Off |
| `--headed` | Show the browser window (useful for debugging) | Headless |

---

## Viewing Results

Results are saved in the `output/` directory:

| File | Description |
|---|---|
| `linkedin_jobs.csv` | Spreadsheet-friendly format |
| `linkedin_jobs.json` | Structured data with full details |
| `index.html` | Interactive web dashboard |

Each record includes: title, company, location, URL, posted date, matched relocation keywords, and a description excerpt.

### Web Dashboard

To view the interactive dashboard, serve the output folder locally:

```bash
cd output
python -m http.server 8080
```

Then open **http://localhost:8080** in your browser. The dashboard supports:

- **Search/filter** by title, company, or location
- **Filter by relocation type** (visa sponsorship, relocation package, etc.)
- **Sort** by date, company, or title
- **Remove/dismiss** jobs you're not interested in (persisted in browser storage)
- **Restore** dismissed jobs with undo or the "restore all" button

---

## Configuration

All settings live in [`config.py`](config.py). Edit this file to customize the scraper's behavior without CLI flags.

### Search Parameters

| Setting | Description | Default |
|---|---|---|
| `SEARCH_KEYWORDS` | LinkedIn search query string | `"senior software engineer relocation"` |
| `LOCATION` | Target geography (leave empty for worldwide) | `""` |
| `GEO_ID` | LinkedIn geo ID for precise targeting (e.g., `"101165590"` for UK) | `""` |

### Title Keywords

The `TITLE_KEYWORDS` list controls which job titles are considered relevant. A job must contain **at least one** of these in its title to pass the filter:

```python
TITLE_KEYWORDS = [
    "senior software engineer",
    "senior software developer",
    "sr. software engineer",
    "sr software engineer",
    "staff software engineer",
    "lead software engineer",
    "senior backend engineer",
    "senior frontend engineer",
    "senior full stack engineer",
    "senior fullstack engineer",
    "senior full-stack engineer",
    "senior swe",
    "senior developer",
]
```

Add or remove entries to adjust what roles are included.

### Relocation Keywords

The `RELOCATION_KEYWORDS` list defines what phrases to look for in job descriptions. A job must mention **at least one** of these to pass the filter:

```python
RELOCATION_KEYWORDS = [
    "relocation",
    "relocation support",
    "relocation assistance",
    "relocation package",
    "visa sponsorship",
    "visa support",
    "work permit",
    "immigration support",
    # ... see config.py for the full list
]
```

### Scraping Settings

| Setting | Description | Default |
|---|---|---|
| `MAX_PAGES` | Maximum listing pages to scrape | `10` |
| `REQUEST_DELAY` | Random delay range (seconds) between requests | `(1, 3)` |
| `HEADLESS_BROWSER` | Run Chrome in headless mode | `True` |
| `PAGE_LOAD_TIMEOUT` | Seconds to wait for a page to load | `30` |

### Output Settings

| Setting | Description | Default |
|---|---|---|
| `OUTPUT_DIR` | Directory for exported files | `"output"` |
| `OUTPUT_CSV` | CSV filename | `"linkedin_jobs.csv"` |
| `OUTPUT_JSON` | JSON filename | `"linkedin_jobs.json"` |

---

## Project Structure

```
LinkedIn Scrapper/
├── main.py              # CLI entry point
├── scraper.py           # Selenium-based LinkedIn scraper
├── filters.py           # Title/relocation filtering + CSV/JSON export
├── config.py            # All configurable settings
├── requirements.txt     # Python dependencies
├── .gitignore
├── README.md
└── output/
    ├── linkedin_jobs.csv
    ├── linkedin_jobs.json
    └── index.html       # Interactive web dashboard
```

---

## Disclaimer

This tool is for **personal, educational use only**. Scraping LinkedIn may violate their [Terms of Service](https://www.linkedin.com/legal/user-agreement). Use responsibly:

- Keep request rates low (the default delay between requests is intentional)
- Don't use this for mass data collection or commercial purposes
- Consider using LinkedIn's official [Job Search API](https://learn.microsoft.com/en-us/linkedin/) if available
