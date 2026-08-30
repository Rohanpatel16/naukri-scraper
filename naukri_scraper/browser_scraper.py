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
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import DEFAULT_HEADERS
from .parser import parse_job_url

logger = logging.getLogger(__name__)

# In-memory runtime cache for company website & linkedin lookups during the active run
_COMPANY_WEBSITE_CACHE: Dict[str, str] = {}
_COMPANY_LINKEDIN_CACHE: Dict[str, str] = {}


def clean_html(text: Optional[str]) -> str:
    """Strip HTML tags and unescape entities into clean plain text."""
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    t = re.sub(r"</(p|li|h\d)>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def clean_company_queries(name: str) -> List[str]:
    """Generates ordered search query variations for Clearbit."""
    candidates: List[str] = []
    raw = name.strip()
    if raw:
        candidates.append(raw)

    # Remove parentheses content e.g. "Willis Towers Watson (WTW)" -> "Willis Towers Watson"
    no_parens = re.sub(r"\(.*?\)", "", raw).strip()
    if no_parens and no_parens not in candidates:
        candidates.append(no_parens)

    # Remove legal/business suffixes
    cleaned = re.sub(
        r"\b(pvt\.?|private|ltd\.?|limited|llc|inc\.?|corp\.?|corporation|group|services|enterprises|technologies|solutions)\b",
        "",
        no_parens,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned not in candidates and len(cleaned) > 2:
        candidates.append(cleaned)

    return candidates


EXCLUDE_DDGS_DOMAINS = [
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "glassdoor", "ambitionbox", "naukri", "indeed", "zaubacorp", "tofler", "crunchbase",
    "zoominfo", "owler", "wikipedia.org", "justdial.com", "indiamart.com", "tradeindia.com",
    "tracxn.com", "companydetails.in", "bing.com", "google.com", "github.com", "play.google.com"
]


def search_company_details_ddgs_sync(company_name: str) -> Tuple[str, str]:
    """Sync helper for DuckDuckGo Search extracting (website, linkedin_url) rapidly."""
    website = ""
    linkedin_url = ""

    # Clean name
    clean = re.sub(r"\(.*?\)", "", company_name)
    clean = re.sub(
        r"\b(pvt\.?|private|ltd\.?|limited|llc|inc\.?|corp\.?|corporation|group|services|enterprises|technologies|solutions)\b",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    clean = re.sub(r"\s+", " ", clean).strip()
    target_name = clean if clean and len(clean) > 2 else company_name

    queries = [
        f"{target_name} official website linkedin"
    ]

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        return "", ""

    for q in queries:
        if website and linkedin_url:
            break
        try:
            with DDGS(timeout=3) as ddgs:
                results = list(ddgs.text(q, max_results=5))
                for r in results:
                    url = r.get("href", "")
                    if not url:
                        continue

                    # Extract LinkedIn company URL
                    if "linkedin.com/company/" in url.lower() and not linkedin_url:
                        linkedin_url = url.split("?")[0].rstrip("/")

                    # Extract official website
                    if not website and not any(ex in url.lower() for ex in EXCLUDE_DDGS_DOMAINS):
                        parsed = urllib.parse.urlparse(url)
                        if parsed.scheme and parsed.netloc:
                            website = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass

    return website, linkedin_url


async def dynamic_extract_ddgs(
    company_name: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, str, str]:
    """Queries DuckDuckGo Search for website and LinkedIn URL."""
    async with semaphore:
        loop = asyncio.get_running_loop()
        web, li = await loop.run_in_executor(None, search_company_details_ddgs_sync, company_name)
        return company_name, web, li


async def dynamic_extract_clearbit(
    client: Any,
    company_name: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, str]:
    """Queries Clearbit Autocomplete API as a fast dynamic fallback (Tier 3)."""
    async with semaphore:
        queries = clean_company_queries(company_name)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        for q in queries:
            encoded_q = urllib.parse.quote(q)
            url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={encoded_q}"
            try:
                if client is not None:
                    resp = await client.get(url, headers=headers, timeout=5.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list) and len(data) > 0:
                            domain = data[0].get("domain", "").strip()
                            if domain:
                                web = f"https://{domain}" if not domain.startswith("http") else domain
                                return company_name, web
            except Exception:
                pass
            await asyncio.sleep(0.04)

        return company_name, ""


async def dynamic_extract_ambitionbox(page: Page, url: str) -> tuple[str, str, bool]:
    """Pure dynamic extraction from AmbitionBox page.
    
    Returns:
        (website_url, linkedin_url, is_page_detected_and_valid)
    """
    website = ""
    linkedin_url = ""
    page_loaded = False
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if resp and resp.status == 404:
            return ("", "", True)  # Confirmed page doesn't exist

        for _ in range(25):
            html_text = await page.content()
            if "__NEXT_DATA__" in html_text or '"website"' in html_text:
                page_loaded = True
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        props = data.get("props", {}).get("pageProps", {})
                        meta = props.get("companyMetaInformation") or props.get("companyHeaderData") or {}
                        raw_w = meta.get("website") or ""
                        if raw_w and isinstance(raw_w, str) and raw_w.strip():
                            raw_w = raw_w.strip()
                            website = f"https://{raw_w}" if not raw_w.startswith("http") else raw_w

                        raw_li = meta.get("linkedinUrl") or meta.get("linkedin") or ""
                        if raw_li and isinstance(raw_li, str) and "linkedin.com/company/" in raw_li:
                            linkedin_url = raw_li.split("?")[0].rstrip("/")
                    except Exception:
                        pass

                if not website:
                    web_m = re.search(r'"website"\s*:\s*"(https?://[^"]+)"', html_text)
                    if web_m:
                        website = web_m.group(1).replace("\\/", "").strip()

                if not linkedin_url:
                    li_m = re.search(r'https?://[a-z]{2,3}\.linkedin\.com/company/[a-zA-Z0-9_\-]+', html_text)
                    if li_m:
                        linkedin_url = li_m.group(0).split("?")[0].rstrip("/")

                if website:
                    break
            await asyncio.sleep(0.1)

    except Exception:
        return ("", "", False)

    return (website, linkedin_url, page_loaded)


async def enrich_company_websites_in_browser(
    jobs: List[Dict[str, Any]],
    context: BrowserContext,
    num_tabs: int = 6,
    max_enrichment_seconds: float = 120.0,
) -> None:
    """Pure dynamic live enrichment with three-tier strategy:
    1. Primary (Tier 1): AmbitionBox live extraction via concurrent browser tabs.
    2. Fallback 1 (Tier 2): DuckDuckGo Search (ddgs) for unlisted/missing companies & LinkedIn URLs.
    3. Fallback 2 (Tier 3): Clearbit Autocomplete API for remaining missing companies.
    - 100% pure dynamic, 0% hardcoding.
    """
    url_to_comp: Dict[str, str] = {}
    all_company_names: Set[str] = set()

    for j in jobs:
        ab_url = j.get("ambition_box_url")
        cname = (j.get("company") or "").strip()
        if cname:
            all_company_names.add(cname)
        if ab_url and ab_url.startswith("http") and ab_url not in url_to_comp:
            url_to_comp[ab_url] = cname or "Company"

    unique_ab_items = list(url_to_comp.items())
    total_ab = len(unique_ab_items)

    print(f"\n[*] Pure dynamic live enrichment (AmbitionBox Tier 1 + DuckDuckGo Tier 2 + Clearbit Tier 3)...", flush=True)
    logger.info("Enriching %d unique company websites dynamically...", max(total_ab, len(all_company_names)))

    completed = 0
    url_to_website: Dict[str, str] = {}
    url_to_linkedin: Dict[str, str] = {}
    comp_to_website: Dict[str, str] = {}
    comp_to_linkedin: Dict[str, str] = {}
    remaining_to_fetch: List[tuple[str, str]] = []

    # Check runtime cache first
    for ab_url, comp_name in unique_ab_items:
        cached_w = _COMPANY_WEBSITE_CACHE.get(ab_url)
        cached_li = _COMPANY_LINKEDIN_CACHE.get(ab_url)
        if cached_w is not None:
            url_to_website[ab_url] = cached_w
            if cached_w:
                comp_to_website[comp_name] = cached_w
            if cached_li:
                url_to_linkedin[ab_url] = cached_li
                comp_to_linkedin[comp_name] = cached_li
            completed += 1
        else:
            remaining_to_fetch.append((ab_url, comp_name))

    # --- Phase 1 (Tier 1): AmbitionBox Concurrent Extraction ---
    if remaining_to_fetch:
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

                    website, linkedin_url, is_detected = await dynamic_extract_ambitionbox(page, ab_url)
                    _COMPANY_WEBSITE_CACHE[ab_url] = website
                    _COMPANY_LINKEDIN_CACHE[ab_url] = linkedin_url
                    url_to_website[ab_url] = website
                    url_to_linkedin[ab_url] = linkedin_url
                    if website:
                        comp_to_website[comp_name] = website
                    if linkedin_url:
                        comp_to_linkedin[comp_name] = linkedin_url
                    completed += 1

                    if website:
                        status_str = f"{website} (AmbitionBox)"
                    elif is_detected:
                        status_str = "[Not listed on AmbitionBox -> checking DuckDuckGo...]"
                    else:
                        status_str = "[Unreachable on AmbitionBox -> checking DuckDuckGo...]"

                    print(f"[{completed}/{total_ab}] {comp_name} -> {status_str}", flush=True)
                    queue.task_done()
                    await asyncio.sleep(0.05)

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
            print(f"[!] Reached max AmbitionBox time limit ({max_enrichment_seconds}s); continuing to fallbacks...", flush=True)

    # --- Phase 2 (Tier 2): DuckDuckGo Search Fallback (Website & LinkedIn) ---
    unresolved_companies = [c for c in all_company_names if not comp_to_website.get(c) or not comp_to_linkedin.get(c)]
    if unresolved_companies:
        print(f"\n[*] Querying DuckDuckGo Search (Tier 2 fallback) for {len(unresolved_companies)} companies...", flush=True)
        ddgs_semaphore = asyncio.Semaphore(8)

        async def run_ddgs_pool():
            tasks = [dynamic_extract_ddgs(c, ddgs_semaphore) for c in unresolved_companies]
            for coro in asyncio.as_completed(tasks):
                cname, ddgs_web, ddgs_li = await coro
                if ddgs_web and not comp_to_website.get(cname):
                    comp_to_website[cname] = ddgs_web
                    print(f"  [+] DuckDuckGo Website Found: {cname} -> {ddgs_web}", flush=True)
                if ddgs_li and not comp_to_linkedin.get(cname):
                    comp_to_linkedin[cname] = ddgs_li
                    print(f"  [+] DuckDuckGo LinkedIn Found: {cname} -> {ddgs_li}", flush=True)

        try:
            await asyncio.wait_for(run_ddgs_pool(), timeout=45.0)
        except asyncio.TimeoutError:
            print("[!] Reached DuckDuckGo time limit (45s); proceeding to Clearbit fallback...", flush=True)

    # --- Phase 3 (Tier 3): Clearbit Autocomplete API Fallback ---
    still_unresolved = [c for c in all_company_names if not comp_to_website.get(c)]
    if still_unresolved:
        print(f"\n[*] Querying Clearbit Autocomplete API (Tier 3 fallback) for {len(still_unresolved)} companies...", flush=True)
        cb_semaphore = asyncio.Semaphore(15)
        try:
            import httpx
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
            async with httpx.AsyncClient(limits=limits, follow_redirects=True) as http_client:
                tasks = [dynamic_extract_clearbit(http_client, c, cb_semaphore) for c in still_unresolved]
                for coro in asyncio.as_completed(tasks):
                    cname, clearbit_web = await coro
                    if clearbit_web and not comp_to_website.get(cname):
                        comp_to_website[cname] = clearbit_web
                        print(f"  [+] Clearbit Website Found: {cname} -> {clearbit_web}", flush=True)
        except Exception:
            pass

    # Assign enriched websites and LinkedIn URLs back to all matching jobs
    found_web_count = 0
    found_li_count = 0
    for job in jobs:
        cname = (job.get("company") or "").strip()
        ab_url = job.get("ambition_box_url", "")
        
        # Priority: Direct company resolution, then AmbitionBox URL resolution
        web = comp_to_website.get(cname) or url_to_website.get(ab_url) or ""
        li_url = comp_to_linkedin.get(cname) or url_to_linkedin.get(ab_url) or ""
        job["company_website"] = web
        job["company_linkedin_url"] = li_url
        if web:
            found_web_count += 1
        if li_url:
            found_li_count += 1

    print(f"\n[+] Finished enrichment: {found_web_count}/{len(jobs)} websites, {found_li_count}/{len(jobs)} LinkedIn URLs resolved.\n", flush=True)


class NaukriBrowserScraper:
    """High-performance parallel browser scraper for Naukri search URLs."""

    def __init__(self, headless: bool = True, timeout_ms: int = 35000, num_workers: int = 3) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.num_workers = max(1, num_workers)

    def _build_page_url(self, base_url: str, page_num: int) -> str:
        """Construct paginated URL for Naukri search.
        
        Handles both clean path URLs (/jobs-in-mumbai -> /jobs-in-mumbai-2)
        and query-based URLs (tech-lead-jobs-in-india?k=... -> tech-lead-jobs-in-india?k=...&pageNo=2)
        without causing router redirect resets.
        """
        if page_num <= 1:
            return base_url

        parsed = urllib.parse.urlparse(base_url)
        query_dict = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        if query_dict or "?" in base_url:
            query_dict["pageNo"] = [str(page_num)]
            new_query = urllib.parse.urlencode(query_dict, doseq=True)
            return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        else:
            clean_path = re.sub(r"-\d+$", "", parsed.path)
            new_path = f"{clean_path}-{page_num}"
            return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))

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
                        "company_linkedin_url": "",
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
                            "company_linkedin_url": "",
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
            await enrich_company_websites_in_browser(all_jobs, context, num_tabs=6, max_enrichment_seconds=120.0)

            try:
                await asyncio.wait_for(context.close(), timeout=4.0)
            except Exception:
                pass
            try:
                await asyncio.wait_for(browser.close(), timeout=4.0)
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
