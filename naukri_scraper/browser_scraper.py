"""Browser-based Scraper for custom Naukri search URLs using Playwright.

Captures all rich fields directly from internal JobAPI responses and DOM:
- Job Title, Company Name, Locations, Experience
- Salary & CTC details
- Skills / Tags
- Job Description Snippet
- AmbitionBox Rating & Review Count
- AmbitionBox Review URL
- Vacancies & Openings
- Freshness badge & Posting Date
- Direct Apply URLs
"""

from __future__ import annotations

import datetime
import html
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

from playwright.sync_api import Browser, Page, sync_playwright

from .config import DEFAULT_HEADERS
from .parser import parse_job_url

logger = logging.getLogger(__name__)


def clean_html(text: Optional[str]) -> str:
    """Strip HTML tags and unescape entities into clean plain text."""
    if not text:
        return ""
    # Convert breaks and list items to spaces
    t = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    t = re.sub(r"</(p|li|h\d)>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


class NaukriBrowserScraper:
    """Scrapes rich job records directly from any custom Naukri search URL."""

    def __init__(self, headless: bool = True, timeout_ms: int = 45000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

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

    def scrape_url(
        self,
        search_url: str,
        max_pages: int = 5,
        max_jobs: int = 100,
    ) -> List[Dict[str, Any]]:
        """Scrape rich jobs from a specific Naukri search URL with pagination.

        Args:
            search_url: Full Naukri search URL.
            max_pages: Maximum number of search pages to paginate through.
            max_jobs: Target maximum number of jobs to return.

        Returns:
            List of structured job dictionaries with all rich fields.
        """
        matched_jobs: List[Dict[str, Any]] = []
        seen_job_ids: Set[str] = set()

        with sync_playwright() as p:
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

                page_api_jobs: List[Dict[str, Any]] = []

                def on_response(response):
                    if "jobapi/v3/search" in response.url or "jobapi" in response.url:
                        try:
                            payload = response.json()
                            job_list = payload.get("jobDetails", [])
                            if job_list:
                                page_api_jobs.extend(job_list)
                        except Exception:
                            pass

                page.on("response", on_response)

                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    page.wait_for_selector(".srp-jobtuple-wrapper, .cust-job-tuple", timeout=20000)
                except Exception as exc:
                    logger.warning("Page %d load timeout or no job cards found: %s", page_num, exc)
                    break

                # 1. Process intercepted JobAPI items (richest data source)
                if page_api_jobs:
                    for raw in page_api_jobs:
                        job_id = str(raw.get("jobId") or "").strip()
                        if not job_id or job_id in seen_job_ids:
                            continue

                        seen_job_ids.add(job_id)

                        # Placeholders (exp, salary, loc)
                        ph_dict = {p.get("type"): p.get("label", "") for p in raw.get("placeholders", []) if isinstance(p, dict)}
                        
                        title = raw.get("title", "").strip()
                        company = raw.get("companyName", "").strip()
                        location = ph_dict.get("location") or raw.get("location", "India")
                        exp_text = ph_dict.get("experience") or raw.get("experienceText", "Not specified")
                        salary = ph_dict.get("salary") or "Not disclosed"

                        # Skills / Tags
                        raw_skills = raw.get("tagsAndSkills", "")
                        if isinstance(raw_skills, list):
                            skills = ", ".join([str(s.get("label", s)) for s in raw_skills])
                        else:
                            skills = str(raw_skills)

                        # Description
                        job_desc = clean_html(raw.get("jobDescription", ""))

                        # AmbitionBox Review Data
                        ab_data = raw.get("ambitionBoxData") or {}
                        company_rating = str(ab_data.get("AggregateRating", "")).strip()
                        reviews_count = str(ab_data.get("ReviewsCount", "")).strip()
                        ambition_box_url = ab_data.get("Url", "")

                        # Vacancies & Freshness
                        vacancies = str(raw.get("vacancy", "")).strip()
                        freshness = raw.get("footerPlaceholderLabel", "").strip()

                        # Posting Date
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

                        # Min / Max Experience numbers
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
                        if jd_url and not jd_url.startswith("http"):
                            full_url = "https://www.naukri.com" + jd_url
                        else:
                            full_url = jd_url

                        record = {
                            "job_id": job_id,
                            "title": title,
                            "company": company,
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
                        }

                        matched_jobs.append(record)

                        if len(matched_jobs) >= max_jobs:
                            logger.info("Reached target limit of %d jobs.", max_jobs)
                            browser.close()
                            return matched_jobs

                # 2. Fallback to DOM elements if API response was missed
                else:
                    cards = page.query_selector_all(".srp-jobtuple-wrapper, .cust-job-tuple")
                    for card in cards:
                        try:
                            title_el = card.query_selector("a.title")
                            if not title_el:
                                continue

                            job_url = title_el.get_attribute("href") or ""
                            parsed = parse_job_url(job_url)
                            job_id = parsed["job_id"] if parsed else str(abs(hash(job_url)))

                            if job_id in seen_job_ids:
                                continue

                            seen_job_ids.add(job_id)

                            comp_el = card.query_selector("a.comp-name, a.company, .comp-name")
                            exp_el = card.query_selector(".expwdth, .exp-wrap, span[class*='exp']")
                            sal_el = card.query_selector(".sal-wrap, .ni-job-tuple-icon-srp-rupee, span[class*='sal']")
                            loc_el = card.query_selector(".loc-wrap, .locWdth, span[class*='loc']")
                            desc_el = card.query_selector(".job-desc, .job-description, .dang-inner-html")
                            rating_el = card.query_selector(".rating, .ambitionBox, span[class*='rating']")
                            reviews_el = card.query_selector(".review, span[class*='review']")

                            # Skills tags in DOM
                            tag_els = card.query_selector_all("ul.tags-gt li, .tag-li, .tagsAndSkills")
                            dom_skills = ", ".join([t.inner_text().strip() for t in tag_els if t.inner_text().strip()])

                            matched_jobs.append({
                                "job_id": job_id,
                                "title": title_el.inner_text().strip(),
                                "company": comp_el.inner_text().strip() if comp_el else "",
                                "location": loc_el.inner_text().strip() if loc_el else "India",
                                "experience_text": exp_el.inner_text().strip() if exp_el else "Not specified",
                                "salary": sal_el.inner_text().strip() if sal_el else "Not disclosed",
                                "skills": dom_skills,
                                "job_description": clean_html(desc_el.inner_text()) if desc_el else "",
                                "company_rating": rating_el.inner_text().strip() if rating_el else "",
                                "company_reviews_count": reviews_el.inner_text().strip() if reviews_el else "",
                                "ambition_box_url": "",
                                "vacancies": "",
                                "freshness": "",
                                "posted_date": parsed["posted_date"] if parsed else "",
                                "min_experience": parsed["min_experience"] if parsed else 0,
                                "max_experience": parsed["max_experience"] if parsed else 99,
                                "url": job_url,
                                "source": "naukri",
                            })

                            if len(matched_jobs) >= max_jobs:
                                logger.info("Reached target limit of %d jobs.", max_jobs)
                                browser.close()
                                return matched_jobs

                        except Exception:
                            continue

                logger.info("Page %d complete. Total collected so far: %d", page_num, len(matched_jobs))
                time.sleep(1.5)

            browser.close()

        logger.info("Finished browser scraping. Total jobs scraped: %d", len(matched_jobs))
        return matched_jobs
