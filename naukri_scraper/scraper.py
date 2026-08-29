import datetime
import gzip
import logging
import re
import time
from typing import Any, Dict, Generator, List, Optional, Set

import requests

from .config import (
    CITY_SITEMAP_MAP,
    DEFAULT_HEADERS,
    NAUKRI_INCREMENTAL_SITEMAP_URL,
    NAUKRI_SITEMAP_INDEX_URL,
)
from .parser import matches_filters, parse_job_url

logger = logging.getLogger(__name__)


class NaukriScraper:
    """Fast, anti-bot resilient scraper for Naukri.com using XML sitemap streams."""

    def __init__(
        self,
        timeout: int = 25,
        max_retries: int = 3,
        retry_delay: float = 1.5,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.headers = headers or DEFAULT_HEADERS.copy()
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _fetch(self, url: str) -> Optional[bytes]:
        """Fetch raw bytes from a URL with retries and exponential backoff."""
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as exc:
                logger.warning("Fetch failed (%d/%d) for %s: %s", attempt, self.max_retries, url, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
        return None

    def get_target_sitemaps(self, location_filter: Optional[str] = None) -> List[str]:
        """Discover relevant sitemap URLs from the index and incremental feeds."""
        sitemaps: List[str] = []

        # 1. Check if location has a dedicated city sitemap
        if location_filter:
            norm_loc = location_filter.lower().strip()
            for city_key, sitemap_name in CITY_SITEMAP_MAP.items():
                if city_key in norm_loc:
                    sitemaps.append(f"https://www.naukri.com/sitemap/{sitemap_name}")
                    logger.info("Found dedicated city sitemap for '%s': %s", city_key, sitemaps[-1])
                    break

        # 2. Always fetch latest fresh jobs from incremental feed
        inc_bytes = self._fetch(NAUKRI_INCREMENTAL_SITEMAP_URL)
        if inc_bytes:
            inc_text = self._decompress_if_needed(inc_bytes, NAUKRI_INCREMENTAL_SITEMAP_URL)
            latest_urls = re.findall(r"<loc>(https?://[^<]+)</loc>", inc_text)
            for u in latest_urls:
                if u not in sitemaps:
                    sitemaps.append(u)

        # 3. Fallback to main sitemap index if still empty or need broader coverage
        if not sitemaps:
            index_bytes = self._fetch(NAUKRI_SITEMAP_INDEX_URL)
            if index_bytes:
                index_text = self._decompress_if_needed(index_bytes, NAUKRI_SITEMAP_INDEX_URL)
                all_sitemaps = re.findall(r"<loc>(https?://[^<]+)</loc>", index_text)
                job_sitemaps = [u for u in all_sitemaps if "jobDescPages" in u or "sitemap-latest" in u]
                sitemaps.extend(job_sitemaps)

        return sitemaps

    def _decompress_if_needed(self, data: bytes, url: str) -> str:
        """Decompress gzip content if detected or requested by URL."""
        if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(data).decode("utf-8", errors="replace")
            except Exception as exc:
                logger.warning("Gzip decompression error on %s: %s", url, exc)
        return data.decode("utf-8", errors="replace")

    def stream_job_urls(self, sitemap_url: str) -> Generator[str, None, None]:
        """Stream individual job URLs from a given sitemap."""
        data = self._fetch(sitemap_url)
        if not data:
            return

        xml_text = self._decompress_if_needed(data, sitemap_url)
        for match in re.finditer(r"<loc>(https?://www\.naukri\.com/job-listings-[^<]+)</loc>", xml_text):
            yield match.group(1)

    def scrape(
        self,
        keywords: Optional[List[str]] = None,
        location: Optional[str] = None,
        experience: Optional[int] = None,
        hours: Optional[int] = None,
        days: Optional[int] = None,
        max_jobs: int = 100,
        max_sitemaps: int = 5,
    ) -> List[Dict[str, Any]]:
        """Scrape matching job listings from Naukri.com.

        Args:
            keywords: Keywords to match in title or company (e.g. ['python', 'devops']).
            location: Target city / location filter (e.g. 'Bangalore', 'Pune', 'Remote').
            experience: Candidate's years of experience (e.g. 3).
            hours: Only include jobs posted within the last N hours (e.g. 24).
            days: Only include jobs posted within the last N days (e.g. 1, 3, 7).
            max_jobs: Maximum number of matching jobs to return.
            max_sitemaps: Maximum number of sitemap files to process.

        Returns:
            List of structured job dictionaries.
        """
        # Calculate since_date cutoff if hours or days filter is set
        since_date: Optional[datetime.date] = None
        if hours is not None or days is not None:
            total_days = (days or 0) + ((hours or 0) / 24.0)
            since_date = datetime.date.today() - datetime.timedelta(days=max(1, int(total_days)))

        target_sitemaps = self.get_target_sitemaps(location_filter=location)[:max_sitemaps]
        logger.info(
            "Processing %d sitemap(s) for filters: keywords=%s, loc=%s, exp=%s, since=%s",
            len(target_sitemaps), keywords, location, experience, since_date
        )

        matched_jobs: List[Dict[str, Any]] = []
        seen_job_ids: Set[str] = set()

        for sitemap_idx, sitemap_url in enumerate(target_sitemaps, 1):
            logger.info("[%d/%d] Reading sitemap: %s", sitemap_idx, len(target_sitemaps), sitemap_url)
            
            for url in self.stream_job_urls(sitemap_url):
                parsed = parse_job_url(url)
                if not parsed:
                    continue

                job_id = parsed["job_id"]
                if job_id in seen_job_ids:
                    continue

                if matches_filters(
                    parsed,
                    keywords=keywords,
                    location_filter=location,
                    experience_filter=experience,
                    since_date=since_date,
                ):
                    seen_job_ids.add(job_id)
                    # Clean temporary helper keys before returning
                    clean_job = {k: v for k, v in parsed.items() if not k.startswith("_")}
                    matched_jobs.append(clean_job)

                    if len(matched_jobs) >= max_jobs:
                        logger.info("Reached target limit of %d jobs.", max_jobs)
                        return matched_jobs

        logger.info("Scraping completed. Found %d matching jobs.", len(matched_jobs))
        return matched_jobs
