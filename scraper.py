"""LinkedIn Job Scraper — fetches job listings from LinkedIn public job search."""

import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus, urlencode

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

logger = logging.getLogger(__name__)


@dataclass
class Job:
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    posted_date: str = ""
    relocation_mentions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "description": self.description[:500],  # truncate for CSV readability
            "posted_date": self.posted_date,
            "relocation_mentions": "; ".join(self.relocation_mentions),
        }


class LinkedInScraper:
    """Scrapes LinkedIn public job search pages."""

    BASE_URL = "https://www.linkedin.com/jobs/search/"

    def __init__(
        self,
        keywords: str | None = None,
        location: str | None = None,
        geo_id: str | None = None,
        max_pages: int | None = None,
        skip_details: bool | None = None,
    ):
        # Per-instance overrides — fall back to module config defaults.
        self.keywords = keywords if keywords is not None else config.SEARCH_KEYWORDS
        self.location = location if location is not None else config.LOCATION
        self.geo_id = geo_id if geo_id is not None else config.GEO_ID
        self.max_pages = max_pages if max_pages is not None else config.MAX_PAGES
        self.skip_details = skip_details if skip_details is not None else config.SKIP_DETAILS

        self.driver = self._init_driver()
        self.jobs: list[Job] = []

    def _init_driver(self) -> webdriver.Chrome:
        opts = Options()
        if config.HEADLESS_BROWSER:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])

        # Container-friendly: respect CHROME_BIN and CHROMEDRIVER env vars
        # (set by the Dockerfile to /usr/bin/chromium and /usr/bin/chromedriver).
        chrome_bin = os.environ.get("CHROME_BIN")
        if chrome_bin:
            opts.binary_location = chrome_bin

        chromedriver = os.environ.get("CHROMEDRIVER")
        if chromedriver:
            service = Service(executable_path=chromedriver)
            driver = webdriver.Chrome(service=service, options=opts)
        else:
            # Selenium 4.6+ has a built-in driver manager — no need for webdriver-manager
            driver = webdriver.Chrome(options=opts)

        driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
        return driver

    def _build_search_url(self, start: int = 0) -> str:
        params: dict[str, str] = {
            "keywords": self.keywords,
            "start": str(start),
        }
        if self.location:
            params["location"] = self.location
        if self.geo_id:
            params["geoId"] = self.geo_id
        return f"{self.BASE_URL}?{urlencode(params, quote_via=quote_plus)}"

    def _random_delay(self):
        lo, hi = config.REQUEST_DELAY
        time.sleep(random.uniform(lo, hi))

    # ------------------------------------------------------------------
    # Listing page helpers
    # ------------------------------------------------------------------

    def _scroll_listing_page(self):
        """Scroll to the bottom of the job listing page to load all cards."""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        for _ in range(5):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # Click "See more jobs" button if present
        try:
            see_more = self.driver.find_element(By.CSS_SELECTOR, "button.infinite-scroller__show-more-button")
            if see_more.is_displayed():
                see_more.click()
                time.sleep(2)
        except Exception:
            pass

    def _parse_listing_cards(self, html: str) -> list[dict]:
        """Extract basic job info from the listing page HTML."""
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.base-card, li.result-card, div.job-search-card")
        results = []
        for card in cards:
            title_el = card.select_one("h3.base-search-card__title, h3.job-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle a, h4.job-search-card__subtitle")
            location_el = card.select_one("span.job-search-card__location")
            link_el = card.select_one("a.base-card__full-link, a.base-search-card__full-link")
            date_el = card.select_one("time")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else ""
            url = link_el["href"].split("?")[0] if link_el and link_el.get("href") else ""
            posted = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""

            if title:
                results.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": url,
                    "posted_date": posted,
                })
        return results

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------

    def _fetch_job_description(self, url: str) -> str:
        """Navigate to a job detail page and return the description text."""
        try:
            self.driver.get(url)
            self._random_delay()

            # Use JS to click "Show more" and extract text — much faster than WebDriverWait
            self.driver.execute_script("""
                var btn = document.querySelector('button.show-more-less-html__button--more');
                if (btn) btn.click();
            """)
            time.sleep(0.5)

            desc_el = self.driver.find_elements(
                By.CSS_SELECTOR,
                "div.show-more-less-html__markup, div.description__text, section.description div.core-section-container__content",
            )
            if desc_el:
                return desc_el[0].text
        except Exception as exc:
            logger.warning("Could not fetch description for %s: %s", url, exc)
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape(self) -> list[Job]:
        """Run the scraper across configured pages."""
        all_cards: list[dict] = []
        seen_urls: set[str] = set()

        for page in range(self.max_pages):
            start = page * 25
            url = self._build_search_url(start)
            logger.info("Fetching listing page %d — %s", page + 1, url)

            try:
                self.driver.get(url)
                self._random_delay()
                self._scroll_listing_page()
                cards = self._parse_listing_cards(self.driver.page_source)
            except Exception as exc:
                logger.error("Error on page %d: %s", page + 1, exc)
                break

            if not cards:
                logger.info("No more jobs found. Stopping at page %d.", page + 1)
                break

            # Deduplicate: only add cards with URLs we haven't seen yet
            new_count = 0
            for card in cards:
                card_url = card.get("url", "")
                if card_url and card_url not in seen_urls:
                    seen_urls.add(card_url)
                    all_cards.append(card)
                    new_count += 1

            logger.info("Collected %d new cards (%d total unique so far).", new_count, len(all_cards))

        # Pre-filter: only fetch details for jobs whose title looks relevant
        title_keywords = [kw.lower() for kw in config.TITLE_KEYWORDS]
        relevant_cards = [
            c for c in all_cards
            if any(kw in c["title"].lower() for kw in title_keywords)
        ]
        logger.info(
            "Total listing cards: %d. Title-matched: %d. Fetching descriptions…",
            len(all_cards), len(relevant_cards),
        )

        if self.skip_details:
            logger.info("Skipping detail page fetches (skip_details=True).")

        for i, card in enumerate(relevant_cards, 1):
            if self.skip_details:
                description = ""
            else:
                logger.info("[%d/%d] Fetching details for: %s", i, len(relevant_cards), card["title"])
                description = self._fetch_job_description(card["url"]) if card["url"] else ""

            job = Job(
                title=card["title"],
                company=card["company"],
                location=card["location"],
                url=card["url"],
                description=description,
                posted_date=card["posted_date"],
            )
            self.jobs.append(job)

        return self.jobs

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass
