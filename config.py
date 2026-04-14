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

# Negative keywords — jobs mentioning these are excluded (no relocation/visa)
RELOCATION_NEGATIVE_KEYWORDS = [
    "no relocation",
    "not offer relocation",
    "not provide relocation",
    "doesn't offer relocation",
    "doesn't provide relocation",
    "does not offer relocation",
    "does not provide relocation",
    "don't offer relocation",
    "do not offer relocation",
    "do not provide relocation",
    "relocation not provided",
    "relocation is not provided",
    "relocation is not available",
    "relocation will not be provided",
    "without relocation",
    "no visa sponsorship",
    "not offer visa",
    "not provide visa",
    "doesn't offer visa",
    "doesn't provide visa",
    "does not offer visa",
    "does not provide visa",
    "don't offer visa",
    "do not offer visa",
    "do not provide visa",
    "don't sponsor",
    "do not sponsor",
    "does not sponsor",
    "will not sponsor",
    "won't sponsor",
    "cannot sponsor",
    "can not sponsor",
    "unable to sponsor",
    "not able to sponsor",
    "unable to provide visa",
    "unable to offer visa",
    "unable to offer relocation",
    "unable to provide relocation",
    "no sponsorship",
    "not eligible for visa",
    "without visa sponsorship",
    "without sponsorship",
    "no immigration support",
    "no work permit",
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
