"""Configuration for the LinkedIn Job Scraper."""

# Search parameters
SEARCH_KEYWORDS = "senior software engineer relocation"
LOCATION = ""  # e.g., "Germany", "Netherlands", "Europe" — leave empty for worldwide
GEO_ID = ""    # LinkedIn geo ID (optional, e.g., "101165590" for United Kingdom)

# Relocation-related keywords to look for in job descriptions
RELOCATION_KEYWORDS = [
    "relocation",
    "relocation support",
    "relocation assistance",
    "relocation package",
    "relocation bonus",
    "visa sponsorship",
    "visa support",
    "work permit",
    "immigration support",
    "moving assistance",
    "relocation allowance",
    "willing to relocate",
    "help you relocate",
    "assist with relocation",
    "relocation stipend",
]

# Job title keywords (at least one must match)
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

# Scraping settings
MAX_PAGES = 10              # Max pages to scrape (25 jobs per page)
REQUEST_DELAY = (1, 3)      # Random delay range in seconds between requests
HEADLESS_BROWSER = True      # Run browser in headless mode
PAGE_LOAD_TIMEOUT = 30       # Seconds to wait for page load

# Output settings
OUTPUT_DIR = "output"
OUTPUT_CSV = "linkedin_jobs.csv"
OUTPUT_JSON = "linkedin_jobs.json"
