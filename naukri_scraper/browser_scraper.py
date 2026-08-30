"""High-Performance Async Multi-Tab Browser Scraper for Naukri.com.

Optimized for high speed, stability on cloud CI/CD runners (GitHub Actions / Linux),
and local environments with 100% pure dynamic data extraction:
- Async parallel multi-tab search scraping
- Stealth browser flags & anti-automation evasion
- 100% pure dynamic live AmbitionBox website extraction (zero hardcoding)
- Accurate detection of listed websites vs companies without a website on AmbitionBox
- Robust route blocking, hard timeouts, and clean resource disposal (guaranteed zero hangs)
"""

from __future__ import annotations

import asyncio
import datetime
import html
import json
import logging
import re
import sys
from typing import Any, Dict, List, Optional, Set

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import DEFAULT_HEADERS
from .parser import parse_job_url

logger = logging.getLogger(__name__)

# In-memory runtime cache for company website lookups during the active run (avoids duplicate network queries)
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


async def dynamic_extract_ambitionbox(page: Page, url: str) -> tuple[str, bool]:
    """Pure dynamic extraction from AmbitionBox page.
    
    Returns:
        (website_url, is_page_detected_and_valid)
    """
    website = ""
    page_loaded = False
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if resp and resp.status == 404:
            return ("", True)  # Confirmed page doesn't exist

        for _ in range(25):
            html_text = await page.content()
            if "__NEXT_DATA__" in html_text or '"website"' in html_text:
                page_loaded = True
                m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text)
                if m:
                    try:
                        d = json.loads(m.group(1))
                        props = d.get("props", {}).get("pageProps", {}) or {}
                        meta = props.get("companyMetaInformation", {}) or {}
                        header = props.get("companyHeaderData", {}) or {}
                        website = (meta.get("website") or header.get("website") or "").strip()
                    except Exception:
                        pass

                if not website:
                    web_m = re.search(r'"website"\s*:\s*"(https?://[^"]+)"', html_text)
                    if web_m:
                        website = web_m.group(1).replace("\\/", "").strip()

                if website:
                    break
            await asyncio.sleep(0.1)

    except Exception:
        return ("", False)

    return (website, page_loaded)


async def enrich_company_websites_in_browser(
    jobs: List[Dict[str, Any]],
    context: BrowserContext,
    num_tabs: int = 3,
    max_enrichment_seconds: float = 180.0,
) -> None:
    """Pure dynamic live enrichment for all company websites directly from AmbitionBox:
    - 0% hardcoding: All websites are retrieved live directly from AmbitionBox.
    - Accurate detection of listed websites vs companies without website entries.
    - Multi-tab queue processing for speed.
    - Guaranteed no-hang with hard timeouts and graceful cleanup.
    """
    url_to_comp: Dict[str, str] = {}
    for j in jobs:
        ab_url = j.get("ambition_box_url")
        cname = (j.get("company") or "").strip()
        if ab_url and ab_url.startswith("http") and ab_url not in url_to_comp:
            url_to_comp[ab_url] = cname or "Company"

    unique_items = list(url_to_comp.items())
    total = len(unique_items)
    if total == 0:
        return

    print(f"\n[*] Pure dynamic live enrichment for {total} unique companies from AmbitionBox...", flush=True)
    logger.info("Enriching %d unique company websites dynamically...", total)

    completed = 0
    url_to_website: Dict[str, str] = {}
    remaining_to_fetch: List[tuple[str, str]] = []

    # Check runtime cache first for previously queried URLs in this session
    for ab_url, comp_name in unique_items:
        if ab_url in _COMPANY_WEBSITE_CACHE:
            url_to_website[ab_url] = _COMPANY_WEBSITE_CACHE[ab_url]
            completed += 1
        else:
            remaining_to_fetch.append((ab_url, comp_name))

    if not remaining_to_fetch:
        for job in jobs:
            ab_url = job.get("ambition_box_url", "")
            if ab_url in url_to_website:
                job["company_website"] = url_to_website[ab_url]
        return

    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    for item in remaining_to_fetch:
        await queue.put(item)

    async def worker_tab(tab_id: int) -> None:
        nonlocal completed
        page: Optional[Page] = None
        try:
            page = await context.new_page()

            async def route_handler(route):
                try:
                    if route.request.resource_type in ["image", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()
                except Exception:
                    pass

            await page.route("**/*", route_handler)

            while not queue.empty():
                try:
                    ab_url, comp_name = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                website, is_detected = await dynamic_extract_ambitionbox(page, ab_url)
                _COMPANY_WEBSITE_CACHE[ab_url] = website
                url_to_website[ab_url] = website
                completed += 1

                if website:
                    status_str = website
                elif is_detected:
                    status_str = "[Not listed on AmbitionBox]"
                else:
                    status_str = "[Page unreachable / no website]"

                print(f"[{completed}/{total}] {comp_name} -> {status_str}", flush=True)
                queue.task_done()
                await asyncio.sleep(0.08)

        except Exception:
            pass
        finally:
            if page:
                try:
                    await page.unroute("**/*")
                    await asyncio.wait_for(page.close(), timeout=3.0)
                except Exception:
                    pass

    actual_tabs = min(num_tabs, len(remaining_to_fetch))
    try:
        await asyncio.wait_for(
            asyncio.gather(*(worker_tab(i) for i in range(actual_tabs))),
            timeout=max_enrichment_seconds,
        )
    except asyncio.TimeoutError:
        print(f"[!] Reached max enrichment time limit ({max_enrichment_seconds}s); proceeding with collected data.", flush=True)

    # Assign enriched websites back to all matching jobs
    found_count = 0
    for job in jobs:
        ab_url = job.get("ambition_box_url", "")
        if ab_url in url_to_website:
            web = url_to_website[ab_url]
            job["company_website"] = web
            if web:
                found_count += 1

    print(f"[+] Finished company website enrichment ({found_count}/{total} websites resolved).\n", flush=True)


class NaukriBrowserScraper:
    """High-performance parallel browser scraper for Naukri search URLs."""

    def __init__(self, headless: bool = True, timeout_ms: int = 35000, num_workers: int = 3) -> None:
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

        # Abort images and media for fast network performance
        async def route_handler(route):
            try:
                if route.request.resource_type in ["image", "media"]:
                    await route.abort()
                else:
                    await route.continue_()
            except Exception:
                pass

        await page.route("**/*", route_handler)

        # Single unified response listener for the lifetime of this page
        latest_page_jobs: List[Dict[str, Any]] = []

        async def on_res(response):
            if "jobapi/v3/search" in response.url or "jobapi" in response.url:
                try:
                    payload = await response.json()
                    jobs = payload.get("jobDetails", [])
                    if jobs:
                        latest_page_jobs.extend(jobs)
                except Exception:
                    pass

        page.on("response", on_res)

        worker_jobs: List[Dict[str, Any]] = []
        consecutive_empty = 0

        # Stagger initial launch slightly between workers
        await asyncio.sleep((worker_id - 1) * 0.4)

        for page_num in page_numbers:
            target_url = self._build_page_url(search_url, page_num)
            latest_page_jobs.clear()

            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout_ms)

                # Wait dynamically for API response payload
                for _ in range(60):
                    if latest_page_jobs:
                        break
                    await asyncio.sleep(0.1)

                if not latest_page_jobs:
                    try:
                        await page.wait_for_selector(".srp-jobtuple-wrapper, .cust-job-tuple", timeout=6000)
                    except Exception:
                        pass

            except Exception as exc:
                logger.debug("[Worker %d] Page %d timeout/exception: %s", worker_id, page_num, exc)

            if latest_page_jobs:
                consecutive_empty = 0
                for raw in latest_page_jobs:
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

                logger.info("[Worker %d] Page %d scraped (%d jobs).", worker_id, page_num, len(latest_page_jobs))
            else:
                # Fallback to DOM elements if API response was missed
                cards = await page.query_selector_all(".srp-jobtuple-wrapper, .cust-job-tuple")
                if not cards:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        logger.info("[Worker %d] Reached end of results at page %d; stopping worker.", worker_id, page_num)
                        break
                    continue

                consecutive_empty = 0
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

        try:
            await page.unroute("**/*")
            await asyncio.wait_for(page.close(), timeout=3.0)
        except Exception:
            pass

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
                    kwargs: Dict[str, Any] = {
                        "headless": self.headless,
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                        ],
                    }
                    if channel:
                        kwargs["channel"] = channel
                    browser = await p.chromium.launch(**kwargs)
                    break
                except Exception:
                    continue

            if not browser:
                logger.error("Could not launch Playwright browser. Please ensure browsers are installed (`playwright install`).")
                return []

            context: BrowserContext = await browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="Asia/Kolkata",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                },
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            # Partition pages among workers (interleaved for load balancing)
            actual_workers = min(self.num_workers, max_pages)
            all_page_nums = list(range(1, max_pages + 1))
            worker_partitions = [all_page_nums[i::actual_workers] for i in range(actual_workers)]

            tasks = [
                self._scrape_tab_worker(w_idx + 1, parts, search_url, context)
                for w_idx, parts in enumerate(worker_partitions)
            ]

            results = await asyncio.gather(*tasks)

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

            # Pure dynamic website enrichment inside active context
            await enrich_company_websites_in_browser(all_jobs, context, num_tabs=3, max_enrichment_seconds=180.0)

            try:
                await asyncio.wait_for(browser.close(), timeout=5.0)
            except Exception:
                pass

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
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._async_scrape_url(search_url, max_pages, max_jobs))
