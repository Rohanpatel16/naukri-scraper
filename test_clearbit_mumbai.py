import asyncio
import csv
import os
import re
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

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

    # Remove legal suffixes
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


async def query_clearbit(
    client: httpx.AsyncClient,
    company_name: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Queries Clearbit Autocomplete API for a company."""
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
                resp = await client.get(url, headers=headers, timeout=6.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        top = data[0]
                        domain = top.get("domain", "").strip()
                        matched_name = top.get("name", "").strip()
                        if domain:
                            # Format domain to full URL if needed
                            website = f"https://{domain}" if not domain.startswith("http") else domain
                            return company_name, website, matched_name
            except Exception:
                pass
            await asyncio.sleep(0.05)

        return company_name, None, None


async def main():
    csv_path = r"d:\Codinf projets\Naukri.com scraper\naukri_mumbai_506_jobs.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        jobs: List[Dict[str, Any]] = list(reader)

    print("=" * 75)
    print(f"[*] CLEARBIT AUTOCOMPLETE DOMAIN RESOLUTION ON {len(jobs)} MUMBAI JOBS")
    print("=" * 75)

    unique_companies = sorted(list(set(j.get("company", "").strip() for j in jobs if j.get("company"))))
    print(f"[*] Total Jobs Rows in CSV    : {len(jobs)}")
    print(f"[*] Total Unique Companies    : {len(unique_companies)}")
    print("=" * 75)

    t0 = time.time()
    semaphore = asyncio.Semaphore(8)  # 8 concurrent requests
    clearbit_results: Dict[str, Optional[str]] = {}

    limits = httpx.Limits(max_keepalive_connections=15, max_connections=20)
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        tasks = [query_clearbit(client, comp, semaphore) for comp in unique_companies]
        
        resolved_count = 0
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            comp, website, matched_name = await coro
            clearbit_results[comp] = website
            if website:
                resolved_count += 1
                print(f"[{i}/{len(unique_companies)}] [+] {comp} -> {website} ({matched_name})")
            else:
                print(f"[{i}/{len(unique_companies)}] [-] {comp} -> [Not found in Clearbit]")

    elapsed = time.time() - t0

    print("\n" + "=" * 75)
    print(f"CLEARBIT EXTRACTION SUMMARY (Completed in {elapsed:.2f}s):")
    print("=" * 75)
    print(f"  * Total Unique Companies Queried : {len(unique_companies)}")
    print(f"  * Companies Found via Clearbit   : {resolved_count} ({resolved_count/len(unique_companies)*100:.1f}%)")
    print(f"  * Companies Not in Clearbit      : {len(unique_companies) - resolved_count}")
    print("=" * 75)

    # Update jobs and save to new CSV with clearbit columns
    if "clearbit_website" not in fieldnames:
        idx = fieldnames.index("company_website") if "company_website" in fieldnames else 3
        fieldnames.insert(idx + 1, "clearbit_website")

    for j in jobs:
        cname = j.get("company", "").strip()
        j["clearbit_website"] = clearbit_results.get(cname, "") or ""

    output_csv = r"d:\Codinf projets\Naukri.com scraper\naukri_mumbai_clearbit_jobs.csv"
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)

    jobs_with_clearbit = sum(1 for j in jobs if j.get("clearbit_website"))
    print(f"[+] Total Jobs with Clearbit Website: {jobs_with_clearbit} / {len(jobs)} ({jobs_with_clearbit/len(jobs)*100:.1f}%)")
    print(f"[+] Output written to: {output_csv}\n")


if __name__ == "__main__":
    asyncio.run(main())
