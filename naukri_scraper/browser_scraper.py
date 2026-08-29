"""Browser-based Scraper for custom Naukri search URLs using Playwright."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

from playwright.sync_api import Browser, Page, sync_playwright

from .config import DEFAULT_HEADERS
from .parser import parse_job_url

logger = logging.getLogger(__name__)


class NaukriBrowserScraper:
    """Scrapes jobs directly from any custom Naukri search URL using Playwright."""

    def __init__(self, headless: bool = True, timeout_ms: int = 45000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    def _build_page_url(self, base_url: str, page_num: int) -> str:
        """Construct paginated URL for Naukri search."""
        if page_num <= 1:
            return base_url

        # Check if URL already has query parameters
        if "?" in base_url:
            path, query = base_url.split("?", 1)
            # e.g., https://www.naukri.com/jobs-in-india -> https://www.naukri.com/jobs-in-india-2
            path = re.sub(r"-\d+$", "", path)
            return f"{path}-{page_num}?{query}"
        else:
            path = re.sub(r"-\d+$", "", base_url)
            return f"{path}-{page_num}"

    def scrape_url(
        self,
        search_url: str,
        max_pages: int = 5,
        max_jobs: int = 100,
    ) -> List[Dict[str, Any]]:
        """Scrape jobs from a specific Naukri search URL with pagination.

        Args:
            search_url: Full Naukri search URL (with functionalArea, jobAge, etc.).
            max_pages: Maximum number of search pages to paginate through.
            max_jobs: Target maximum number of jobs to return.

        Returns:
            List of structured job dictionaries.
        """
        matched_jobs: List[Dict[str, Any]] = []
        seen_job_ids: Set[str] = set()

        with sync_playwright() as p:
            # Try to launch Edge/Chrome channel, fallback to default chromium
            browser: Optional[Browser] = None
            for channel in ["msedge", "chrome", None]:
                try:
                    kwargs = {"headless": self.headless}
                    if channel:
                        kwargs["channel"] = channel
                    browser = p.chromium.launch(**kwargs)
                    break
                except Exception:
                    continue

            if not browser:
                logger.error("Could not launch Playwright browser. Please run `playwright install chromium`.")
                return []

            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
            )
            page: Page = context.new_page()

            for page_num in range(1, max_pages + 1):
                target_url = self._build_page_url(search_url, page_num)
                logger.info("[%d/%d] Scraping page: %s", page_num, max_pages, target_url)

                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    page.wait_for_selector(".srp-jobtuple-wrapper, .cust-job-tuple", timeout=20000)
                except Exception as exc:
                    logger.warning("Page %d load timeout or no job cards found: %s", page_num, exc)
                    break

                # Extract job card DOM elements
                cards = page.query_selector_all(".srp-jobtuple-wrapper, .cust-job-tuple")
                if not cards:
                    logger.info("No job cards found on page %d; stopping pagination.", page_num)
                    break

                page_jobs_count = 0
                for card in cards:
                    try:
                        title_el = card.query_selector("a.title")
                        if not title_el:
                            continue

                        title = title_el.inner_text().strip()
                        job_url = title_el.get_attribute("href") or ""
                        if not job_url:
                            continue

                        # Extract Job ID and date from URL or fallback
                        parsed = parse_job_url(job_url)
                        job_id = parsed["job_id"] if parsed else str(abs(hash(job_url)))

                        if job_id in seen_job_ids:
                            continue

                        seen_job_ids.add(job_id)

                        comp_el = card.query_selector("a.comp-name, a.company, .comp-name")
                        company = comp_el.inner_text().strip() if comp_el else (parsed["company"] if parsed else "")

                        exp_el = card.query_selector(".expwdth, .exp-wrap, span[class*='exp']")
                        exp_text = exp_el.inner_text().strip() if exp_el else (parsed["experience_text"] if parsed else "Not specified")

                        loc_el = card.query_selector(".loc-wrap, .locWdth, span[class*='loc']")
                        location = loc_el.inner_text().strip() if loc_el else (parsed["location"] if parsed else "India")

                        job_record = {
                            "job_id": job_id,
                            "title": title,
                            "company": company,
                            "location": location,
                            "min_experience": parsed["min_experience"] if parsed else 0,
                            "max_experience": parsed["max_experience"] if parsed else 99,
                            "experience_text": exp_text,
                            "posted_date": parsed["posted_date"] if parsed else "",
                            "url": job_url,
                            "source": "naukri",
                        }

                        matched_jobs.append(job_record)
                        page_jobs_count += 1

                        if len(matched_jobs) >= max_jobs:
                            logger.info("Reached target limit of %d jobs.", max_jobs)
                            browser.close()
                            return matched_jobs

                    except Exception as e:
                        logger.debug("Error extracting card: %s", e)
                        continue

                logger.info("Page %d yielded %d unique jobs.", page_num, page_jobs_count)
                time.sleep(1.5)

            browser.close()

        logger.info("Finished browser scraping. Total jobs scraped: %d", len(matched_jobs))
        return matched_jobs
