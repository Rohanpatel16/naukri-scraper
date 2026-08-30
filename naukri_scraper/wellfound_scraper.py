"""Wellfound.com job scraper — extracts unique companies with websites, LinkedIn URLs, and open jobs."""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
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

WELLFOUND_FIELDS = [
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

EXCLUDE_DDGS_DOMAINS = [
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "glassdoor", "ambitionbox", "naukri", "indeed", "zaubacorp", "tofler", "crunchbase",
    "zoominfo", "owler", "wikipedia.org", "justdial.com", "indiamart.com", "tradeindia.com",
    "tracxn.com", "companydetails.in", "bing.com", "google.com", "github.com", "play.google.com",
    "wellfound.com", "angel.co"
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

    try:
        with DDGS(timeout=4) as ddgs:
            results = list(ddgs.text(f"{target_name} official website linkedin", max_results=6))
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

    # Check total results count
    m2 = re.search(r"([\d,]+)\s+results?\s+total", text, re.I)
    if m2:
        total = int(m2.group(1).replace(",", ""))
        return max(1, (total + 19) // 20)
    return 1


def _parse_listing_page(
    html: str,
    base_url: str,
    max_days: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Parse a Wellfound listing page and extract company + job data with time filtering."""
    soup = BeautifulSoup(html, "html.parser")
    companies: List[Dict[str, Any]] = []

    company_links = soup.find_all("a", href=re.compile(r"^/company/[^/]+$"))
    seen_slugs = set()

    for a in company_links:
        slug = a.get("href", "").strip()
        cname = a.get_text(strip=True)
        if not cname or not slug or slug in seen_slugs or "Explore" in cname:
            continue
        seen_slugs.add(slug)

        comp: Dict[str, Any] = {
            "company_name": cname,
            "company_website": "",
            "company_linkedin_url": "",
            "total_jobs_posted": 0,
            "job_titles": [],
            "posted_dates": [],
            "wellfound_job_urls": [],
            "locations": set(),
            "salaries": set(),
            "equity": set(),
            "stage": "",
            "employee_count": "",
        }

        # Walk up to find enclosing card container
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

        if found_card:
            # Employee count
            emp_el = found_card.find(string=re.compile(r"\d+[\d,]*\s*[–-]\s*\d+\s*Employees?|\d+\s*Employees?", re.I))
            if emp_el:
                comp["employee_count"] = emp_el.strip()

            # Stage tags
            stage_tags = found_card.find_all(["span", "a", "div"], string=re.compile(r"Stage|Series|Seed|Growth|Late", re.I))
            if stage_tags:
                comp["stage"] = stage_tags[0].get_text(strip=True)

            # Job titles & URLs with date parsing
            job_links = found_card.find_all("a", href=re.compile(r"^/jobs/\d+"))
            for jlink in job_links:
                title = jlink.get_text(strip=True)
                href = jlink.get("href", "")
                if not title or not href:
                    continue

                # Find posted date around the job link
                parent = jlink.find_parent()
                ptext = parent.get_text(" | ", strip=True) if parent else ""
                
                # Check up 2 levels for the date element
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

                # Check max_days filter
                if max_days is not None and date_str:
                    age = parse_posted_age_days(date_str)
                    if age > max_days:
                        continue  # Skip jobs older than max_days

                if title not in comp["job_titles"]:
                    comp["job_titles"].append(title)
                    comp["posted_dates"].append(date_str or "Recent")

                full_url = f"https://wellfound.com{href}" if href.startswith("/") else href
                if full_url not in comp["wellfound_job_urls"]:
                    comp["wellfound_job_urls"].append(full_url)

                if parent:
                    ptext_plain = parent.get_text(" ", strip=True)
                    sal_m = re.search(r"\$[\d,]+k?\s*[-–]\s*\$[\d,]+k?", ptext_plain, re.I)
                    if sal_m:
                        comp["salaries"].add(sal_m.group(0))
                    eq_m = re.search(r"[\d.]+%\s*[-–]\s*[\d.]+%", ptext_plain)
                    if eq_m:
                        comp["equity"].add(eq_m.group(0))
                    loc_m = re.search(r"(?:In office|Remote|Hybrid)\s*[•·]\s*([^•·$\n]+)", ptext_plain)
                    if loc_m:
                        comp["locations"].add(loc_m.group(1).strip())

        comp["total_jobs_posted"] = len(comp["job_titles"])
        if comp["total_jobs_posted"] > 0:
            companies.append(comp)

    return companies


class WellfoundScraper:
    """Playwright-based scraper for Wellfound.com."""

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
    ) -> List[Dict[str, Any]]:
        """Main async scraper coordinator with optional time filtering."""
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

            # Collect pages
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

        # Parse all raw companies with freshness filter
        raw_companies: List[Dict[str, Any]] = []
        for pnum in sorted(all_pages_html.keys()):
            html = all_pages_html[pnum]
            if html:
                page_comps = _parse_listing_page(html, page1_url, max_days=max_days_filter)
                raw_companies.extend(page_comps)

        # Aggregate unique companies
        agg: Dict[str, Dict[str, Any]] = {}
        for comp in raw_companies:
            cname = comp["company_name"]
            if not cname:
                continue
            if cname not in agg:
                agg[cname] = comp
                agg[cname]["locations"] = set(comp["locations"])
                agg[cname]["salaries"] = set(comp["salaries"])
                agg[cname]["equity"] = set(comp["equity"])
            else:
                existing = agg[cname]
                existing["total_jobs_posted"] += comp["total_jobs_posted"]
                for i, t in enumerate(comp["job_titles"]):
                    if t not in existing["job_titles"]:
                        existing["job_titles"].append(t)
                        if i < len(comp["posted_dates"]):
                            existing["posted_dates"].append(comp["posted_dates"][i])
                for u in comp["wellfound_job_urls"]:
                    if u not in existing["wellfound_job_urls"]:
                        existing["wellfound_job_urls"].append(u)
                existing["locations"].update(comp["locations"])
                existing["salaries"].update(comp["salaries"])
                existing["equity"].update(comp["equity"])
                if not existing["stage"] and comp["stage"]:
                    existing["stage"] = comp["stage"]
                if not existing["employee_count"] and comp["employee_count"]:
                    existing["employee_count"] = comp["employee_count"]

        unique_companies_list = list(agg.values())
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
    ) -> List[Dict[str, Any]]:
        """Public synchronous entry point."""
        try:
            return asyncio.run(self._async_scrape(search_url, max_pages, days, hours))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._async_scrape(search_url, max_pages, days, hours))
