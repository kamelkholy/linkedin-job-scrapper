#!/usr/bin/env python3
"""
LinkedIn Job Scraper — Main entry point.

Searches LinkedIn for senior software engineering jobs with relocation support,
filters results, and exports to CSV + JSON.
"""

import argparse
import logging
import sys

import config
from filters import export_csv, export_json, filter_jobs
from scraper import LinkedInScraper


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Scrape LinkedIn for senior SWE jobs with relocation support.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--keywords", type=str, default=None, help="Override search keywords.")
    parser.add_argument("--location", type=str, default=None, help="Override search location.")
    parser.add_argument("--pages", type=int, default=None, help="Override max pages to scrape.")
    parser.add_argument("--no-filter", action="store_true", help="Export all jobs without filtering.")
    parser.add_argument("--skip-details", action="store_true", help="Skip fetching full job details/descriptions.")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed (visible) mode.")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("main")

    # Apply CLI overrides
    if args.keywords:
        config.SEARCH_KEYWORDS = args.keywords
    if args.location:
        config.LOCATION = args.location
    if args.pages:
        config.MAX_PAGES = args.pages
    if args.headed:
        config.HEADLESS_BROWSER = False
    if args.skip_details:
        config.SKIP_DETAILS = True

    logger.info("=== LinkedIn Job Scraper ===")
    logger.info("Keywords : %s", config.SEARCH_KEYWORDS)
    logger.info("Location : %s", config.LOCATION or "(worldwide)")
    logger.info("Max pages: %d", config.MAX_PAGES)

    scraper = LinkedInScraper()
    try:
        jobs = scraper.scrape()
        logger.info("Scraped %d total jobs.", len(jobs))

        if args.no_filter:
            filtered = jobs
        else:
            filtered = filter_jobs(jobs)

        if not filtered:
            logger.warning("No jobs matched the filter criteria.")
        else:
            export_csv(filtered)
            export_json(filtered)
            logger.info("Done! %d matching jobs exported to '%s/'.", len(filtered), config.OUTPUT_DIR)

            # Print summary to console
            print("\n" + "=" * 80)
            print(f"  Found {len(filtered)} senior SWE jobs with relocation support")
            print("=" * 80)
            for i, job in enumerate(filtered, 1):
                print(f"\n{i}. {job.title}")
                print(f"   Company  : {job.company}")
                print(f"   Location : {job.location}")
                print(f"   Relocation: {', '.join(job.relocation_mentions)}")
                print(f"   URL      : {job.url}")
            print()

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(1)
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
