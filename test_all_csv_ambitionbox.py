"""Pure Dynamic Test Tool for all 1644 jobs in naukri_jobs.csv.

Extracts company websites live from AmbitionBox with 0% hardcoding.
"""

import asyncio
import csv
import os
import sys
import time
from typing import Any, Dict, List

from playwright.async_api import async_playwright
from naukri_scraper.browser_scraper import (
    _COMPANY_WEBSITE_CACHE,
    enrich_company_websites_in_browser,
)


async def main():
    csv_path = r"d:\Codinf projets\Naukri.com scraper\naukri_jobs.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        jobs: List[Dict[str, Any]] = list(reader)

    print("=" * 70)
    print(f"[*] PURE DYNAMIC LIVE ENRICHMENT (0% HARDCODING) ON {len(jobs)} JOBS")
    print("=" * 70)

    url_to_comp: Dict[str, str] = {}
    for j in jobs:
        ab_url = j.get("ambition_box_url", "").strip()
        cname = j.get("company", "").strip()
        if ab_url and ab_url.startswith("http") and ab_url not in url_to_comp:
            url_to_comp[ab_url] = cname or "Company"

    print(f"[*] Total Rows in CSV           : {len(jobs)}")
    print(f"[*] Rows with AmbitionBox URL   : {sum(1 for j in jobs if j.get('ambition_box_url'))}")
    print(f"[*] Unique AmbitionBox URLs     : {len(url_to_comp)}")
    print(f"[*] Unique Company Names        : {len(set(j.get('company') for j in jobs if j.get('company')))}")
    print("=" * 70)

    t0 = time.time()

    async with async_playwright() as p:
        browser = None
        for ch in ["msedge", "chrome", None]:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    channel=ch,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                break
            except Exception:
                continue

        if not browser:
            print("[ERROR] Could not launch Playwright Chromium.")
            return

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        await enrich_company_websites_in_browser(
            jobs,
            context,
            num_tabs=3,
            max_enrichment_seconds=180.0,
        )

        try:
            await asyncio.wait_for(browser.close(), timeout=5.0)
        except Exception:
            pass

    elapsed = time.time() - t0

    # Calculate statistics
    resolved_jobs = sum(1 for j in jobs if j.get("company_website"))
    resolved_companies = sum(1 for url, web in _COMPANY_WEBSITE_CACHE.items() if web)

    print("\n" + "=" * 70)
    print(f"RESULTS SUMMARY (Completed in {elapsed:.2f} seconds):")
    print("=" * 70)
    print(f"  * Total Jobs Processed        : {len(jobs)}")
    print(f"  * Jobs with Official Website  : {resolved_jobs} ({resolved_jobs/len(jobs)*100:.1f}%)")
    print(f"  * Unique Companies Resolved   : {resolved_companies} / {len(url_to_comp)}")
    print("=" * 70)

    # Save enriched CSV
    output_path = r"d:\Codinf projets\Naukri.com scraper\naukri_jobs_enriched.csv"
    if "company_website" not in fieldnames:
        idx = fieldnames.index("company") if "company" in fieldnames else 2
        fieldnames.insert(idx + 1, "company_website")

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)

    print(f"[+] Saved enriched data to: {output_path}\n")


if __name__ == "__main__":
    asyncio.run(main())
