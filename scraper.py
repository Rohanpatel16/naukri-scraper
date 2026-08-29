"""Naukri Scraper - CLI & Main Entry Point.

Run this script to scrape jobs from Naukri.com using either:
1. Fast XML sitemaps (no anti-bot blocks, supports keywords, locations, experience, 24h filter)
2. Direct search URLs via Playwright browser automation
"""

from __future__ import annotations

import sys
from naukri_scraper.cli import main

if __name__ == "__main__":
    sys.exit(main())
