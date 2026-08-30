"""CLI for the Wellfound job scraper — paste any Wellfound URL and get a company CSV."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(asctime)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner() -> None:
    print("""
============================================================
           WELLFOUND.COM JOB SCRAPER
============================================================
""")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Wellfound.com for unique company data. Paste any Wellfound URL."
    )
    parser.add_argument(
        "-u", "--url",
        required=True,
        help=(
            "Wellfound search URL. Examples:\n"
            "  https://wellfound.com/role/l/software-engineer/india\n"
            "  https://wellfound.com/jobs?locations=India\n"
            "  https://wellfound.com/location/india"
        ),
    )
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Max pages to scrape (default: all pages)",
    )
    parser.add_argument(
        "-D", "--days",
        type=int,
        default=None,
        help="Only include jobs posted within the last N days (e.g. -D 3, -D 7, -D 14)",
    )
    parser.add_argument(
        "-H", "--hours",
        type=int,
        default=None,
        help="Only include jobs posted within the last N hours (e.g. -H 24, -H 48)",
    )
    parser.add_argument(
        "-o", "--output",
        default="wellfound_companies.csv",
        help="Output CSV file (default: wellfound_companies.csv)",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=3,
        help="Parallel browser tabs (default: 3)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logs",
    )
    return parser.parse_args(argv)


FIELDS = [
    "company_name",
    "company_website",
    "company_linkedin_url",
    "total_jobs_posted",
    "job_titles",
    "posted_dates",
    "wellfound_job_urls",
    "locations",
    "salaries",
    "equity",
    "stage",
    "employee_count",
]


def save_to_csv(companies: List[dict], output: str) -> Path:
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(companies)
    logger.info("Saved %d unique companies to CSV: %s", len(companies), out_path.resolve())
    return out_path


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    print_banner()

    print(f"[*] Target URL  : {args.url}")
    pages_str = str(args.pages) if args.pages else "Auto-detect (all pages)"
    print(f"[*] Pages       : {pages_str}")

    time_filter_str = "All Time"
    if args.hours:
        time_filter_str = f"Last {args.hours} Hours"
    elif args.days:
        time_filter_str = f"Last {args.days} Days"
    print(f"[*] Time Filter : {time_filter_str}")
    print(f"[*] Output File : {args.output}")
    print("-" * 60)

    from .wellfound_scraper import WellfoundScraper

    start = time.time()
    scraper = WellfoundScraper(headless=True, num_workers=args.workers)
    companies = scraper.scrape(
        search_url=args.url,
        max_pages=args.pages,
        days=args.days,
        hours=args.hours,
    )
    elapsed = time.time() - start

    if not companies:
        print("[!] No companies found matching the current filters.")
        return 0

    out_path = save_to_csv(companies, args.output)

    total_jobs = sum(c.get("total_jobs_posted", 0) for c in companies)
    resolved_websites = sum(1 for c in companies if c.get("company_website"))
    pct = resolved_websites / len(companies) * 100 if companies else 0

    print("\n" + "=" * 60)
    print(f"[+] Finished in {elapsed:.1f} seconds.")
    print(f"[+] Unique Companies  : {len(companies):,}")
    print(f"[+] Total Job Postings: {total_jobs:,}")
    print(f"[+] Website Coverage  : {resolved_websites}/{len(companies)} ({pct:.0f}%)")
    print(f"[+] Saved to          : {out_path.resolve()}")
    print("=" * 60)

    # Preview top companies
    print("\nTop Hiring Companies:")
    print("-" * 60)
    for i, c in enumerate(companies[:5], 1):
        print(f"#{i} {c['company_name']} ({c['total_jobs_posted']} jobs)")
        if c.get("stage"):
            print(f"   Stage     : {c['stage']}")
        if c.get("company_website"):
            print(f"   Website   : {c['company_website']}")
        if c.get("company_linkedin_url"):
            print(f"   LinkedIn  : {c['company_linkedin_url']}")
        if c.get("job_titles"):
            titles_preview = c["job_titles"][:80]
            print(f"   Roles     : {titles_preview}...")
        if c.get("posted_dates"):
            print(f"   Posted    : {c['posted_dates']}")
        if c.get("locations"):
            print(f"   Locations : {c['locations']}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
