"""Remote-jobs scraper — finds remote openings at a curated list of companies.

Uses the existing public LinkedIn job-search endpoint, but applies the
``f_WT=2`` work-type filter ("Remote"). For each company we:

1. Search LinkedIn jobs with the company name as the keyword (or the
   slug-derived display name when only a slug is known).
2. Restrict results to the company itself by post-filtering on the
   parsed company name from each card (case/whitespace-insensitive).
3. Skip the title pre-filter so we capture every role at that company,
   not just senior SWE.

The orchestrator (``run_remote_scrape_now`` in ``scheduler.py``) calls
this once per enabled company and feeds results back into the shared
jobs DB with ``source="remote"`` so the UI can filter on the new tab.
"""

from __future__ import annotations

import logging
import re

from scraper import Job, LinkedInScraper

logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


class RemoteJobScraper(LinkedInScraper):
    """LinkedIn search restricted to remote jobs at a single company."""

    def __init__(
        self,
        company_name: str,
        company_slug: str = "",
        max_pages: int = 2,
        skip_details: bool = True,
    ):
        self.company_name = (company_name or company_slug or "").strip()
        self.company_slug = (company_slug or "").strip().lower()

        # Build the keyword: prefer the human display name when present
        # because LinkedIn matches that against the company field.
        keyword = self.company_name or self.company_slug

        super().__init__(
            keywords=keyword,
            location="",
            geo_id="",
            max_pages=max_pages,
            skip_details=skip_details,
            title_keywords=[],            # accept every role at the company
            extra_params={"f_WT": "2"},  # 2 = "Remote" work type filter
        )

    def scrape(self) -> list[Job]:
        jobs = super().scrape()
        target = _norm(self.company_name)
        slug = _norm(self.company_slug)
        kept: list[Job] = []
        for job in jobs:
            company_norm = _norm(job.company)
            if not company_norm:
                continue
            if (target and (target in company_norm or company_norm in target)) or (
                slug and (slug in company_norm or company_norm in slug)
            ):
                kept.append(job)
        logger.info(
            "Remote scrape — company=%s scraped=%d kept=%d",
            self.company_name, len(jobs), len(kept),
        )
        return kept
