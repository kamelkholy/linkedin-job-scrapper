"""Filtering and export utilities for scraped LinkedIn jobs."""

import csv
import json
import logging
import os
import re

import config
from scraper import Job

logger = logging.getLogger(__name__)


def matches_title(job: Job) -> bool:
    """Check whether the job title matches any of the configured title keywords."""
    title_lower = job.title.lower()
    return any(kw in title_lower for kw in config.TITLE_KEYWORDS)


def find_relocation_mentions(job: Job) -> list[str]:
    """Return which relocation keywords appear in the job description or title."""
    text = f"{job.title} {job.description}".lower()
    found = []
    for kw in config.RELOCATION_KEYWORDS:
        if kw in text:
            found.append(kw)
    return found


def filter_jobs(jobs: list[Job]) -> list[Job]:
    """Keep only jobs that match title criteria AND mention relocation."""
    filtered: list[Job] = []
    for job in jobs:
        if not matches_title(job):
            logger.debug("Title mismatch — skipping: %s", job.title)
            continue

        mentions = find_relocation_mentions(job)
        if not mentions:
            logger.debug("No relocation keywords — skipping: %s", job.title)
            continue

        job.relocation_mentions = mentions
        filtered.append(job)

    logger.info(
        "Filtering complete: %d/%d jobs matched criteria.",
        len(filtered),
        len(jobs),
    )
    return filtered


def export_csv(jobs: list[Job], filepath: str | None = None):
    """Export jobs to a CSV file."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    filepath = filepath or os.path.join(config.OUTPUT_DIR, config.OUTPUT_CSV)

    fieldnames = ["title", "company", "location", "url", "posted_date", "relocation_mentions", "description"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            writer.writerow(job.to_dict())

    logger.info("CSV exported to %s (%d jobs).", filepath, len(jobs))


def export_json(jobs: list[Job], filepath: str | None = None):
    """Export jobs to a JSON file."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    filepath = filepath or os.path.join(config.OUTPUT_DIR, config.OUTPUT_JSON)

    data = [job.to_dict() for job in jobs]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("JSON exported to %s (%d jobs).", filepath, len(jobs))
