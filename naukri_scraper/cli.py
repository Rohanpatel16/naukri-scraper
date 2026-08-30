"""Command-Line Interface for the Naukri Scraper."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import List, Optional

from .browser_scraper import NaukriBrowserScraper
from .exporter import save_to_csv, save_to_json
from .scraper import NaukriScraper


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(asctime)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner() -> None:
    banner = """
============================================================
              NAUKRI.COM FAST JOB SCRAPER
============================================================
"""
    print(banner)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fast, anti-bot resilient job scraper for Naukri.com."
    )
    parser.add_argument(
        "-u", "--url",
        default=None,
        help="Direct Naukri search URL (e.g. https://www.naukri.com/jobs-in-india?functionAreaIdGid=4...)",
    )
    parser.add_argument(
        "-p", "--pages",
        type=int,
        default=None,
        help="Pages to scrape (default: auto-detect and scrape all available pages)",
    )
    parser.add_argument(
        "-k", "--keywords",
        nargs="+",
        default=["python"],
        help="Job title or technology keywords to search (e.g. -k python devops aws)",
    )
    parser.add_argument(
        "-l", "--location",
        default=None,
        help="City or location filter (e.g. -l Bangalore, -l Pune, -l Remote)",
    )
    parser.add_argument(
        "-e", "--experience",
        type=int,
        default=None,
        help="Filter jobs matching specific years of experience (e.g. -e 3)",
    )
    parser.add_argument(
        "-H", "--hours",
        type=int,
        default=None,
        help="Only include jobs posted within the last N hours (e.g. -H 24)",
    )
    parser.add_argument(
        "-D", "--days",
        type=int,
        default=None,
        help="Only include jobs posted within the last N days (e.g. -D 1, -D 3)",
    )
    parser.add_argument(
        "-n", "--max-jobs",
        type=int,
        default=None,
        help="Maximum jobs to collect (default: collect all available jobs)",
    )
    parser.add_argument(
        "-s", "--max-sitemaps",
        type=int,
        default=5,
        help="Maximum number of sitemap files to search (default: 5)",
    )
    parser.add_argument(
        "-o", "--output",
        default="naukri_jobs.csv",
        help="Output filepath (e.g. jobs.csv or jobs.json)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed debug logs",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    print_banner()

    start_time = time.time()

    if args.url:
        pages_str = str(args.pages) if args.pages else "Auto-detect (all matching pages)"
        max_jobs_str = str(args.max_jobs) if args.max_jobs else "All matching jobs"
        print(f"[*] Target Custom URL : {args.url}")
        print(f"[*] Search Pages      : {pages_str}")
        print(f"[*] Target Max Jobs   : {max_jobs_str}")
        print(f"[*] Output File       : {args.output}\n" + "-" * 60)

        browser_scraper = NaukriBrowserScraper()
        jobs = browser_scraper.scrape_url(
            search_url=args.url,
            max_pages=args.pages,
            max_jobs=args.max_jobs,
        )
    else:
        time_filter_str = "All Time"
        if args.hours:
            time_filter_str = f"Last {args.hours} Hours"
        elif args.days:
            time_filter_str = f"Last {args.days} Days"

        effective_max_jobs = args.max_jobs or 50
        print(f"[*] Search Keywords : {', '.join(args.keywords)}")
        print(f"[*] Location Filter : {args.location or 'All Locations'}")
        print(f"[*] Experience      : {args.experience if args.experience is not None else 'Any'}")
        print(f"[*] Time Filter     : {time_filter_str}")
        print(f"[*] Target Max Jobs : {effective_max_jobs}")
        print(f"[*] Output File     : {args.output}\n" + "-" * 60)

        scraper = NaukriScraper()
        jobs = scraper.scrape(
            keywords=args.keywords,
            location=args.location,
            experience=args.experience,
            hours=args.hours,
            days=args.days,
            max_jobs=effective_max_jobs,
            max_sitemaps=args.max_sitemaps,
        )

    elapsed = time.time() - start_time

    found_websites = sum(1 for j in jobs if j.get("company_website"))
    unique_companies = len(set(j.get("company") for j in jobs if (j.get("company") or "").strip()))
    pct_web = (found_websites / len(jobs) * 100.0) if jobs else 0.0

    print("-" * 60)
    print(f"[+] Scraping finished in {elapsed:.2f} seconds.")
    print(f"[+] Total Jobs Collected   : {len(jobs):,}")
    print(f"[+] Total Unique Companies : {unique_companies:,}")
    print(f"[+] Website Resolution Rate: {found_websites:,}/{len(jobs):,} jobs ({pct_web:.1f}% coverage)")

    # Save results
    if args.output.endswith(".json"):
        out_path = save_to_json(jobs, args.output)
    else:
        out_path = save_to_csv(jobs, args.output)

    if not jobs:
        print("[!] No matching jobs found with current filters. Try broader keywords or locations.")
        return 0

    print(f"\n[+] Results saved to: {out_path.resolve()}\n")

    # Display preview of top 5 jobs
    print("Top Matches Preview:")
    print("=" * 60)
    for i, job in enumerate(jobs[:5], 1):
        print(f"#{i} {job['title']}")
        if job.get('company'):
            print(f"   Company : {job['company']}")
        print(f"   Location: {job['location']} | Experience: {job['experience_text']}")
        print(f"   URL     : {job['url']}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
