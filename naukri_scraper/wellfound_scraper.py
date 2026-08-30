"""Wellfound.com job scraper — Dump & Filter architecture with dynamic website + LinkedIn enrichment."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

WELLFOUND_COMPANY_FIELDS = [
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

# Comprehensive filter list: ignore directories, social platforms, and aggregator sites
EXCLUDE_DDGS_DOMAINS = [
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "glassdoor", "ambitionbox", "naukri", "indeed", "zaubacorp", "tofler", "crunchbase",
    "zoominfo", "owler", "wikipedia.org", "justdial.com", "indiamart.com", "tradeindia.com",
    "tracxn.com", "companydetails.in", "bing.com", "google.com", "github.com", "play.google.com",
    "wellfound.com", "angel.co", "yourstory.com", "remoterocketship.com", "scribd.com",
    "unstop.com", "leadiq.com", "rocketreach.co", "signalhire.com", "dealroom.co",
    "preqin.com", "cbinsights.com", "g2.com", "volza.com", "datanyze.com", "apollo.io",
    "craft.co", "pitchbook.com", "instahyre.com", "cutshort.io", "shine.com", "hirist.com",
    "internshala.com", "foundit.in", "timesjobs.com", "theorg.com", "ycombinator.com"
]


def parse_posted_age_days(text: str) -> float:
    """Calculates age in days from posted date strings like '4 days ago', '2 weeks ago', '3 hours ago'."""
    if not text:
        return 999.0
    text = text.lower().strip()
    if "just now" in text or "today" in text:
        return 0.0
    if "yesterday" in text:
        return 1.0

    m_h = re.search(r"(\d+)\s*(?:hours?|hrs?|h)\s*ago", text)
    if m_h:
        return float(m_h.group(1)) / 24.0

    m_m = re.search(r"(\d+)\s*(?:mins?|minutes?|m)\s*ago", text)
    if m_m:
        return float(m_m.group(1)) / 1440.0

    m_d = re.search(r"(\d+)\s*(?:days?|d)\s*ago", text)
    if m_d:
        return float(m_d.group(1))

    m_w = re.search(r"(\d+)\s*(?:weeks?|w)\s*ago", text)
    if m_w:
        return float(m_w.group(1)) * 7.0

    m_mo = re.search(r"(\d+)\s*(?:months?|mo)\s*ago", text)
    if m_mo:
        return float(m_mo.group(1)) * 30.0

    return 999.0


def clean_company_name_for_search(company_name: str) -> str:
    clean = re.sub(r"\(.*?\)", "", company_name)
    clean = re.sub(
        r"\b(pvt\.?|private|ltd\.?|limited|llc|inc\.?|corp\.?|corporation|group|services|enterprises|technologies|solutions)\b",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean if clean and len(clean) > 2 else company_name


def search_wellfound_company_details_sync(company_name: str) -> Tuple[str, str, str]:
    """Sync DDGS search extracting both official website and LinkedIn company URL."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return company_name, "", ""

    target_name = clean_company_name_for_search(company_name)
    website = ""
    linkedin = ""

    # Query 1: Search for official website + linkedin
    try:
        with DDGS(timeout=4) as ddgs:
            results = list(ddgs.text(f"{target_name} official website linkedin", max_results=8))
            for r in results:
                url = r.get("href", "")
                if not url:
                    continue

                if "linkedin.com/company" in url.lower() and not linkedin:
                    m = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[a-zA-Z0-9_\-]+", url)
                    if m:
                        linkedin = m.group(0)

                elif not website and not any(ex in url.lower() for ex in EXCLUDE_DDGS_DOMAINS):
                    parsed = urllib.parse.urlparse(url)
                    if parsed.scheme and parsed.netloc:
                        website = f"{parsed.scheme}://{parsed.netloc}"

                if website and linkedin:
                    break

            # Query 2 (if LinkedIn still missing): Search targeted LinkedIn query
            if not linkedin:
                li_results = list(ddgs.text(f'"{target_name}" site:linkedin.com/company', max_results=3))
                for r in li_results:
                    url = r.get("href", "")
                    if "linkedin.com/company" in url.lower():
                        m = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[a-zA-Z0-9_\-]+", url)
                        if m:
                            linkedin = m.group(0)
                            break
    except Exception:
        pass

    return company_name, website, linkedin


async def dynamic_extract_clearbit_single(client: httpx.AsyncClient, company_name: str) -> str:
    """Clearbit Autocomplete fallback for official domain."""
    target_name = clean_company_name_for_search(company_name)
    queries = [target_name, company_name]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    for q in queries:
        try:
            encoded_q = urllib.parse.quote(q)
            url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={encoded_q}"
            resp = await client.get(url, headers=headers, timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    domain = data[0].get("domain", "").strip()
                    if domain:
                        return f"https://{domain}" if not domain.startswith("http") else domain
        except Exception:
            pass
    return ""


def _extract_page_count(html: str) -> int:
    """Extract total pages from 'Page X of Y' text in the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", text, re.I)
    if m:
        return int(m.group(1))

    m2 = re.search(r"([\d,]+)\s+results?\s+total", text, re.I)
    if m2:
        total = int(m2.group(1).replace(",", ""))
        return max(1, (total + 19) // 20)
    return 1


def _extract_raw_jobs_from_html(html: str, base_url: str, page_number: int = 1) -> List[Dict[str, Any]]:
    """Extracts 100% of raw structured data from listing HTML (Dump Phase)."""
    soup = BeautifulSoup(html, "html.parser")
    raw_jobs: List[Dict[str, Any]] = []

    company_links = soup.find_all("a", href=re.compile(r"^/company/[^/]+$"))
    seen_slugs = set()

    for a in company_links:
        slug = a.get("href", "").strip()
        cname = a.get_text(strip=True)
        if not cname or not slug or slug in seen_slugs or "Explore" in cname:
            continue
        seen_slugs.add(slug)

        card = a
        found_card = None
        for _ in range(7):
            if not card.parent:
                break
            card = card.parent
            jobs = card.find_all("a", href=re.compile(r"^/jobs/\d+"))
            other_comps = [
                l.get("href")
                for l in card.find_all("a", href=re.compile(r"^/company/[^/]+$"))
                if l.get("href") != slug
            ]
            if jobs and len(other_comps) == 0:
                found_card = card
                break

        if not found_card:
            found_card = card

        emp_count = ""
        stage = ""
        tagline = ""

        if found_card:
            emp_el = found_card.find(string=re.compile(r"\d+[\d,]*\s*[–-]\s*\d+\s*Employees?|\d+\s*Employees?", re.I))
            if emp_el:
                emp_count = emp_el.strip()

            stage_tags = found_card.find_all(["span", "a", "div"], string=re.compile(r"Stage|Series|Seed|Growth|Late|Public", re.I))
            if stage_tags:
                stage = stage_tags[0].get_text(strip=True)

            job_links = found_card.find_all("a", href=re.compile(r"^/jobs/\d+"))
            for jlink in job_links:
                title = jlink.get_text(strip=True)
                href = jlink.get("href", "")
                if not title or not href:
                    continue

                job_id_m = re.search(r"/jobs/(\d+)", href)
                job_id = job_id_m.group(1) if job_id_m else ""

                parent = jlink.find_parent()
                ptext = parent.get_text(" | ", strip=True) if parent else ""

                date_str = ""
                curr = parent
                for _ in range(3):
                    if not curr:
                        break
                    dm = re.search(r"(\d+\s*(?:days?|weeks?|months?|hours?|mins?|minutes?|d|w|h|m)\s*ago|yesterday|today|just now)", curr.get_text(" | ", strip=True), re.I)
                    if dm:
                        date_str = dm.group(0).strip()
                        break
                    curr = curr.parent

                sal_m = re.search(r"\$[\d,]+k?\s*[-–]\s*\$[\d,]+k?", ptext, re.I)
                salary = sal_m.group(0) if sal_m else ""

                eq_m = re.search(r"[\d.]+%\s*[-–]\s*[\d.]+%", ptext)
                equity = eq_m.group(0) if eq_m else ""

                loc_m = re.search(r"(?:In office|Remote|Hybrid)\s*[•·]\s*([^•·$\n|]+)", ptext)
                location = loc_m.group(1).strip() if loc_m else ""

                type_m = re.search(r"(Full-time|Part-time|Contract|Internship|Intern)", ptext, re.I)
                job_type = type_m.group(1) if type_m else ""

                raw_jobs.append({
                    "page_number": page_number,
                    "company_name": cname,
                    "company_slug": slug,
                    "stage": stage,
                    "employee_count": emp_count,
                    "job_id": job_id,
                    "job_title": title,
                    "job_url": f"https://wellfound.com{href}" if href.startswith("/") else href,
                    "job_type": job_type,
                    "salary": salary,
                    "equity": equity,
                    "location": location,
                    "posted_date_raw": date_str,
                    "posted_age_days": parse_posted_age_days(date_str),
                })

    return raw_jobs


def filter_and_aggregate_companies(
    raw_jobs: List[Dict[str, Any]],
    max_days: Optional[float] = None,
    location_filter: Optional[str] = None,
    keyword_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Applies filters to the raw job dump and aggregates by unique company (Filter Phase)."""
    agg: Dict[str, Dict[str, Any]] = {}

    for j in raw_jobs:
        # Time filter
        if max_days is not None and j.get("posted_date_raw"):
            if j.get("posted_age_days", 999.0) > max_days:
                continue

        # Location filter
        if location_filter and location_filter.lower() not in (j.get("location") or "").lower():
            continue

        # Keyword filter
        if keyword_filter and keyword_filter.lower() not in (j.get("job_title") or "").lower():
            continue

        cname = j["company_name"]
        if not cname:
            continue

        if cname not in agg:
            agg[cname] = {
                "company_name": cname,
                "company_slug": j.get("company_slug", ""),
                "company_website": "",
                "company_linkedin_url": "",
                "total_jobs_posted": 0,
                "job_titles": [],
                "posted_dates": [],
                "wellfound_job_urls": [],
                "locations": set(),
                "salaries": set(),
                "equity": set(),
                "stage": j.get("stage", ""),
                "employee_count": j.get("employee_count", ""),
            }

        rec = agg[cname]
        rec["total_jobs_posted"] += 1
        
        t = j.get("job_title", "")
        if t and t not in rec["job_titles"]:
            rec["job_titles"].append(t)
            rec["posted_dates"].append(j.get("posted_date_raw") or "Recent")

        u = j.get("job_url", "")
        if u and u not in rec["wellfound_job_urls"]:
            rec["wellfound_job_urls"].append(u)

        if j.get("location"):
            rec["locations"].add(j["location"])
        if j.get("salary"):
            rec["salaries"].add(j["salary"])
        if j.get("equity"):
            rec["equity"].add(j["equity"])
        if not rec["stage"] and j.get("stage"):
            rec["stage"] = j["stage"]
        if not rec["employee_count"] and j.get("employee_count"):
            rec["employee_count"] = j["employee_count"]

    return list(agg.values())


class WellfoundScraper:
    """Playwright-based scraper for Wellfound.com using Dump & Filter method."""

    def __init__(self, headless: bool = True, num_workers: int = 3):
        self.headless = headless
        self.num_workers = num_workers

    async def _scrape_page(self, page: Page, url: str) -> str:
        """Navigate to a URL and return rendered HTML."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3500)
            return await page.content()
        except Exception as e:
            logger.warning("Failed to load %s: %s", url, e)
            return ""

    async def _async_scrape(
        self,
        search_url: str,
        max_pages: Optional[int] = None,
        days: Optional[int] = None,
        hours: Optional[int] = None,
        raw_dump_path: Optional[str] = "raw_wellfound_dump.json",
    ) -> List[Dict[str, Any]]:
        """Main async Dump & Filter coordinator."""
        max_days_filter: Optional[float] = None
        if hours is not None and hours > 0:
            max_days_filter = hours / 24.0
        elif days is not None and days > 0:
            max_days_filter = float(days)

        async with async_playwright() as p:
            browser = None
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
                logger.error("Could not launch browser.")
                return []

            context: BrowserContext = await browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            async def route_handler(route):
                try:
                    if route.request.resource_type in ["image", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()
                except Exception:
                    pass

            await context.route("**/*", route_handler)

            # Step 1: Load Page 1
            page1 = await context.new_page()
            page1_url = search_url if "page=" not in search_url else re.sub(r"[?&]page=\d+", "", search_url)
            print(f"[*] Wellfound: Loading Page 1 -> {page1_url}", flush=True)

            html1 = await self._scrape_page(page1, page1_url)
            await page1.close()

            if not html1:
                await browser.close()
                return []

            total_pages = _extract_page_count(html1)

            results_m = re.search(r"([\d,]+)\s+results?\s+total", html1, re.I)
            total_results = int(results_m.group(1).replace(",", "")) if results_m else "?"

            if max_pages and max_pages > 0:
                target_pages = min(max_pages, total_pages)
            else:
                target_pages = total_pages

            print(f"[*] Wellfound: {total_results} total results across {total_pages} pages (scraping {target_pages} pages)...\n", flush=True)

            # Collect raw HTML across parallel workers
            all_pages_html: Dict[int, str] = {1: html1}

            if target_pages > 1:
                queue: asyncio.Queue[Tuple[int, str]] = asyncio.Queue()
                for pnum in range(2, target_pages + 1):
                    sep = "&" if "?" in page1_url else "?"
                    purl = f"{page1_url}{sep}page={pnum}"
                    await queue.put((pnum, purl))

                results_lock = asyncio.Lock()

                async def worker(wid: int) -> None:
                    wp = await context.new_page()
                    while not queue.empty():
                        try:
                            pnum, purl = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        html = await self._scrape_page(wp, purl)
                        async with results_lock:
                            all_pages_html[pnum] = html
                        print(f"[INFO] [Worker {wid}] Page {pnum}/{target_pages} scraped.", flush=True)
                        queue.task_done()
                    await wp.close()

                actual_workers = min(self.num_workers, target_pages - 1)
                await asyncio.gather(*(worker(i + 1) for i in range(actual_workers)))

            await context.close()
            await browser.close()

        # ==========================================
        # PHASE 1: DUMP ALL RAW DATA
        # ==========================================
        all_raw_jobs: List[Dict[str, Any]] = []
        for pnum in sorted(all_pages_html.keys()):
            html = all_pages_html[pnum]
            if html:
                p_jobs = _extract_raw_jobs_from_html(html, page1_url, page_number=pnum)
                all_raw_jobs.extend(p_jobs)

        print(f"\n[+] Raw Data Collection: Extracted {len(all_raw_jobs):,} total raw job records.", flush=True)
        if raw_dump_path:
            try:
                out_raw = Path(raw_dump_path)
                with out_raw.open("w", encoding="utf-8") as f:
                    json.dump(all_raw_jobs, f, indent=2)
                print(f"[+] Saved complete raw dump to: {out_raw.resolve()}", flush=True)
            except Exception as e:
                logger.warning("Could not save raw dump: %s", e)

        # ==========================================
        # PHASE 2: FILTER & AGGREGATE
        # ==========================================
        unique_companies_list = filter_and_aggregate_companies(
            raw_jobs=all_raw_jobs,
            max_days=max_days_filter,
        )

        time_desc = f"last {hours} hours" if hours else (f"last {days} days" if days else "all time")
        print(f"\n[*] Filter Phase ({time_desc}): Kept {len(unique_companies_list):,} unique companies matching criteria.", flush=True)

        if not unique_companies_list:
            return []

        # ==========================================
        # PHASE 3: DYNAMIC LIVE ENRICHMENT
        # ==========================================
        print(f"\n[*] Pure dynamic live enrichment (DuckDuckGo + LinkedIn + Clearbit)...", flush=True)
        print(f"[INFO] Enriching {len(unique_companies_list)} unique companies with Websites and LinkedIn URLs...", flush=True)

        sem = asyncio.Semaphore(6)
        loop = asyncio.get_running_loop()

        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as http_client:
            async def enrich_single(comp: Dict[str, Any]) -> None:
                cname = comp["company_name"]
                async with sem:
                    _, site, li = await loop.run_in_executor(None, search_wellfound_company_details_sync, cname)
                    if not site:
                        site = await dynamic_extract_clearbit_single(http_client, cname)

                    comp["company_website"] = site
                    comp["company_linkedin_url"] = li

                    status_parts = []
                    if site:
                        status_parts.append(f"Web: {site}")
                    if li:
                        status_parts.append(f"LinkedIn: {li}")
                    status_str = " | ".join(status_parts) if status_parts else "[Website not found]"
                    print(f"  [+] {cname} -> {status_str}", flush=True)

            await asyncio.gather(*(enrich_single(c) for c in unique_companies_list))

        # Flatten for CSV export
        flat: List[Dict[str, Any]] = []
        sorted_comps = sorted(unique_companies_list, key=lambda x: x["total_jobs_posted"], reverse=True)
        for comp in sorted_comps:
            flat.append({
                "company_name": comp["company_name"],
                "company_website": comp.get("company_website", ""),
                "company_linkedin_url": comp.get("company_linkedin_url", ""),
                "total_jobs_posted": comp["total_jobs_posted"],
                "job_titles": " | ".join(comp["job_titles"]),
                "posted_dates": " | ".join(comp.get("posted_dates", [])),
                "wellfound_job_urls": " | ".join(comp["wellfound_job_urls"]),
                "locations": ", ".join(sorted(comp["locations"])),
                "salaries": ", ".join(sorted(comp["salaries"])) if comp["salaries"] else "Not disclosed",
                "equity": ", ".join(sorted(comp["equity"])) if comp["equity"] else "Not disclosed",
                "stage": comp.get("stage", ""),
                "employee_count": comp.get("employee_count", ""),
            })

        return flat

    def scrape(
        self,
        search_url: str,
        max_pages: Optional[int] = None,
        days: Optional[int] = None,
        hours: Optional[int] = None,
        raw_dump_path: Optional[str] = "raw_wellfound_dump.json",
    ) -> List[Dict[str, Any]]:
        """Public synchronous entry point."""
        try:
            return asyncio.run(self._async_scrape(search_url, max_pages, days, hours, raw_dump_path))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._async_scrape(search_url, max_pages, days, hours, raw_dump_path))
