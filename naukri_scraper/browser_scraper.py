"""High-Performance Async Multi-Tab Browser Scraper for Naukri.com.

Features:
- Async parallel multi-tab scraping (3-5 concurrent page workers)
- Media/font asset blocking to eliminate network overhead
- Real-time internal JobAPI JSON interception (100% data fidelity)
- Parallel ThreadPool website enrichment for unique companies
- Robust early-exit when no more pages exist
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import html
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

import requests
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import DEFAULT_HEADERS
from .parser import parse_job_url

logger = logging.getLogger(__name__)

# Global cache for company website lookups
_COMPANY_WEBSITE_CACHE: Dict[str, str] = {}


def clean_html(text: Optional[str]) -> str:
    """Strip HTML tags and unescape entities into clean plain text."""
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    t = re.sub(r"</(p|li|h\d)>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def fetch_single_website(overview_url: str) -> tuple[str, str]:
    """Fetch official company website from AmbitionBox Overview page via fast HTTP."""
    if not overview_url:
        return overview_url, ""
    if overview_url in _COMPANY_WEBSITE_CACHE:
        return overview_url, _COMPANY_WEBSITE_CACHE[overview_url]

    try:
        res = requests.get(overview_url, headers=DEFAULT_HEADERS, timeout=5)
        if res.status_code == 200:
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
            if m:
                payload = json.loads(m.group(1))
                props = payload.get("props", {}).get("pageProps", {})
                meta = props.get("companyMetaInformation", {})
                header = props.get("companyHeaderData", {})
                website = (meta.get("website") or header.get("website") or "").strip()
                _COMPANY_WEBSITE_CACHE[overview_url] = website
                return overview_url, website
    except Exception:
        pass

    _COMPANY_WEBSITE_CACHE[overview_url] = ""
    return overview_url, ""


def enrich_company_websites_parallel(jobs: List[Dict[str, Any]], max_workers: int = 15) -> None:
    """Enrich all jobs with company websites in parallel for unique overview URLs."""
    unique_urls = list({j.get("ambition_box_url") for j in jobs if j.get("ambition_box_url")})
    if not unique_urls:
        return

    logger.info("Enriching %d unique company websites in parallel...", len(unique_urls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(fetch_single_website, unique_urls))

    url_to_website = dict(results)
    for job in jobs:
        ab_url = job.get("ambition_box_url", "")
        if ab_url in url_to_website:
            job["company_website"] = url_to_website[ab_url]


class NaukriBrowserScraper:
    """High-performance parallel browser scraper for Naukri search URLs."""

    def __init__(self, headless: bool = True, timeout_ms: int = 30000, num_workers: int = 4) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.num_workers = max(1, num_workers)

    def _build_page_url(self, base_url: str, page_num: int) -> str:
        """Construct paginated URL for Naukri search."""
        if page_num <= 1:
            return base_url

        if "?" in base_url:
            path, query = base_url.split("?", 1)
            path = re.sub(r"-\d+$", "", path)
            return f"{path}-{page_num}?{query}"
        else:
            path = re.sub(r"-\d+$", "", base_url)
            return f"{path}-{page_num}"

    async def _scrape_tab_worker(
        self,
        worker_id: int,
        page_numbers: List[int],
        search_url: str,
        context: BrowserContext,
    ) -> List[Dict[str, Any]]:
        """Worker task to scrape a subset of pages on its own tab."""
        page: Page = await context.new_page()

        # Abort images, fonts, and media for maximum network speed
        async def route_handler(route):
            if route.request.resource_type in ["image", "media", "font"]:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)
        worker_jobs: List[Dict[str, Any]] = []

        for page_num in page_numbers:
            target_url = self._build_page_url(search_url, page_num)
            page_api_jobs: List[Dict[str, Any]] = []

            async def on_res(response):
                if "jobapi/v3/search" in response.url or "jobapi" in response.url:
                    try:
                        payload = await response.json()
                        jobs = payload.get("jobDetails", [])
                        if jobs:
                            page_api_jobs.extend(jobs)
                    except Exception:
                        pass

            page.on("response", on_res)

            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout_ms)

                # Wait dynamically for API response payload (up to 3.5s)
                for _ in range(35):
                    if page_api_jobs:
                        break
                    await asyncio.sleep(0.1)

                if not page_api_jobs:
                    try:
                        await page.wait_for_selector(".srp-jobtuple-wrapper, .cust-job-tuple", timeout=3000)
                    except Exception:
                        pass

            except Exception as exc:
                logger.debug("[Worker %d] Page %d load timeout: %s", worker_id, page_num, exc)
                break

            if page_api_jobs:
                for raw in page_api_jobs:
                    job_id = str(raw.get("jobId") or "").strip()
                    if not job_id:
                        continue

                    ph_dict = {p.get("type"): p.get("label", "") for p in raw.get("placeholders", []) if isinstance(p, dict)}
                    title = raw.get("title", "").strip()
                    company = raw.get("companyName", "").strip()
                    location = ph_dict.get("location") or raw.get("location", "India")
                    exp_text = ph_dict.get("experience") or raw.get("experienceText", "Not specified")
                    salary = ph_dict.get("salary") or "Not disclosed"

                    raw_skills = raw.get("tagsAndSkills", "")
                    skills = ", ".join([str(s.get("label", s)) for s in raw_skills]) if isinstance(raw_skills, list) else str(raw_skills)

                    job_desc = clean_html(raw.get("jobDescription", ""))

                    ab_data = raw.get("ambitionBoxData") or {}
                    company_rating = str(ab_data.get("AggregateRating", "")).strip()
                    reviews_count = str(ab_data.get("ReviewsCount", "")).strip()
                    raw_ab_url = ab_data.get("Url", "")
                    ambition_box_url = ""
                    if raw_ab_url:
                        clean_ab = raw_ab_url.split("?")[0]
                        ambition_box_url = re.sub(
                            r"/reviews/([a-zA-Z0-9_-]+)-reviews",
                            r"/overview/\1-overview",
                            clean_ab,
                        )

                    vacancies = str(raw.get("vacancy", "")).strip()
                    freshness = raw.get("footerPlaceholderLabel", "").strip()

                    created_ts = raw.get("createdDate")
                    posted_date = ""
                    if created_ts:
                        try:
                            posted_date = datetime.datetime.fromtimestamp(created_ts / 1000.0).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    if not posted_date and len(job_id) >= 6:
                        parsed_tmp = parse_job_url(f"https://www.naukri.com/job-listings-{job_id}")
                        if parsed_tmp:
                            posted_date = parsed_tmp.get("posted_date", "")

                    min_exp = 0
                    max_exp = 99
                    try:
                        if raw.get("minimumExperience") is not None:
                            min_exp = int(raw["minimumExperience"])
                        if raw.get("maximumExperience") is not None:
                            max_exp = int(raw["maximumExperience"])
                    except (ValueError, TypeError):
                        pass

                    jd_url = raw.get("jdURL", "")
                    full_url = "https://www.naukri.com" + jd_url if jd_url and not jd_url.startswith("http") else jd_url

                    worker_jobs.append({
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "company_website": "",
                        "location": location,
                        "experience_text": exp_text,
                        "salary": salary,
                        "skills": skills,
                        "job_description": job_desc,
                        "company_rating": company_rating,
                        "company_reviews_count": reviews_count,
                        "ambition_box_url": ambition_box_url,
                        "vacancies": vacancies,
                        "freshness": freshness,
                        "posted_date": posted_date,
                        "min_experience": min_exp,
                        "max_experience": max_exp,
                        "url": full_url,
                        "source": "naukri",
                    })

                logger.info("[Worker %d] Page %d scraped (%d jobs).", worker_id, page_num, len(page_api_jobs))
            else:
                # Fallback to DOM elements if API response was missed
                cards = await page.query_selector_all(".srp-jobtuple-wrapper, .cust-job-tuple")
                if not cards:
                    logger.info("[Worker %d] No cards on page %d; stopping worker.", worker_id, page_num)
                    break

                for card in cards:
                    try:
                        title_el = await card.query_selector("a.title")
                        if not title_el:
                            continue
                        job_url = (await title_el.get_attribute("href")) or ""
                        parsed = parse_job_url(job_url)
                        job_id = parsed["job_id"] if parsed else str(abs(hash(job_url)))

                        comp_el = await card.query_selector("a.comp-name, a.company, .comp-name")
                        exp_el = await card.query_selector(".expwdth, .exp-wrap, span[class*='exp']")
                        sal_el = await card.query_selector(".sal-wrap, span[class*='sal']")
                        loc_el = await card.query_selector(".loc-wrap, span[class*='loc']")
                        desc_el = await card.query_selector(".job-desc, .job-description, .dang-inner-html")
                        rating_el = await card.query_selector(".rating, span[class*='rating']")
                        reviews_el = await card.query_selector(".review, span[class*='review']")

                        tag_els = await card.query_selector_all("ul.tags-gt li, .tag-li")
                        dom_skills = ", ".join([(await t.inner_text()).strip() for t in tag_els if (await t.inner_text()).strip()])

                        worker_jobs.append({
                            "job_id": job_id,
                            "title": (await title_el.inner_text()).strip(),
                            "company": (await comp_el.inner_text()).strip() if comp_el else "",
                            "company_website": "",
                            "location": (await loc_el.inner_text()).strip() if loc_el else "India",
                            "experience_text": (await exp_el.inner_text()).strip() if exp_el else "Not specified",
                            "salary": (await sal_el.inner_text()).strip() if sal_el else "Not disclosed",
                            "skills": dom_skills,
                            "job_description": clean_html(await desc_el.inner_text()) if desc_el else "",
                            "company_rating": (await rating_el.inner_text()).strip() if rating_el else "",
                            "company_reviews_count": (await reviews_el.inner_text()).strip() if reviews_el else "",
                            "ambition_box_url": "",
                            "vacancies": "",
                            "freshness": "",
                            "posted_date": parsed["posted_date"] if parsed else "",
                            "min_experience": parsed["min_experience"] if parsed else 0,
                            "max_experience": parsed["max_experience"] if parsed else 99,
                            "url": job_url,
                            "source": "naukri",
                        })
                    except Exception:
                        continue

        await page.close()
        return worker_jobs

    async def _async_scrape_url(
        self,
        search_url: str,
        max_pages: int = 5,
        max_jobs: int = 100,
    ) -> List[Dict[str, Any]]:
        """Internal asynchronous multi-tab coordinator."""
        async with async_playwright() as p:
            browser: Optional[Browser] = None
            for channel in ["msedge", "chrome", None]:
                try:
                    kwargs = {"headless": self.headless}
                    if channel:
                        kwargs["channel"] = channel
                    browser = await p.chromium.launch(**kwargs)
                    break
                except Exception:
                    continue

            if not browser:
                logger.error("Could not launch Playwright browser.")
                return []

            context: BrowserContext = await browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
            )

            # Partition pages among workers (interleaved for load balancing)
            actual_workers = min(self.num_workers, max_pages)
            all_page_nums = list(range(1, max_pages + 1))
            worker_partitions = [all_page_nums[i::actual_workers] for i in range(actual_workers)]

            tasks = [
                self._scrape_tab_worker(w_idx + 1, parts, search_url, context)
                for w_idx, parts in enumerate(worker_partitions)
            ]

            results = await asyncio.gather(*tasks)
            await browser.close()

        # Deduplicate and cap results
        all_jobs: List[Dict[str, Any]] = []
        seen_job_ids: Set[str] = set()

        for worker_res in results:
            for job in worker_res:
                jid = job.get("job_id")
                if jid and jid not in seen_job_ids:
                    seen_job_ids.add(jid)
                    all_jobs.append(job)
                    if len(all_jobs) >= max_jobs:
                        break
            if len(all_jobs) >= max_jobs:
                break

        # Fast parallel company website enrichment
        enrich_company_websites_parallel(all_jobs)

        logger.info("Scraped %d unique jobs across %d pages.", len(all_jobs), max_pages)
        return all_jobs

    def scrape_url(
        self,
        search_url: str,
        max_pages: int = 5,
        max_jobs: int = 100,
    ) -> List[Dict[str, Any]]:
        """Synchronous public entry point for CLI and external callers."""
        try:
            return asyncio.run(self._async_scrape_url(search_url, max_pages, max_jobs))
        except RuntimeError:
            # If an event loop is already running in the current thread
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._async_scrape_url(search_url, max_pages, max_jobs))
