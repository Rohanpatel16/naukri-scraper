"""Robust, Fast CLI diagnostic tool to test AmbitionBox company data and website extraction.

Can be run locally or via GitHub Actions workflow dispatch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from typing import Any, Dict

from playwright.async_api import async_playwright


async def test_ambitionbox_url(url: str) -> Dict[str, Any]:
    """Test extracting company metadata and official website from AmbitionBox URL."""
    print("=" * 70)
    print(f"[*] Testing AmbitionBox URL : {url}")
    print("=" * 70)

    start_time = time.time()
    extracted_data: Dict[str, Any] = {}

    async with async_playwright() as p:
        browser = None
        for channel in ["msedge", "chrome", None]:
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    channel=channel,
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
            return {}

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        page = await context.new_page()

        # Abort images and media to save bandwidth and speed up page load
        async def route_handler(route):
            if route.request.resource_type in ["image", "media"]:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)

        print("[*] Loading page...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Extract from page HTML safely (never throws Execution Context Destroyed)
            for _ in range(40):
                html_text = await page.content()
                if "__NEXT_DATA__" in html_text or '"website"' in html_text:
                    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text)
                    if m:
                        try:
                            d = json.loads(m.group(1))
                            props = d.get("props", {}).get("pageProps", {}) or {}
                            meta = props.get("companyMetaInformation", {}) or {}
                            header = props.get("companyHeaderData", {}) or {}
                            about = props.get("companyAbout", {}) or {}

                            extracted_data = {
                                "Company Name": header.get("name") or header.get("companyName") or "",
                                "Official Website": (meta.get("website") or header.get("website") or "").strip(),
                                "Rating": str(header.get("rating") or header.get("companyRating") or ""),
                                "Reviews Count": str(header.get("reviewsCount") or header.get("totalReviews") or ""),
                                "Industry": meta.get("industry") or header.get("industry") or "",
                                "Headquarters": meta.get("headquarters") or header.get("hq") or "",
                                "Ownership / Type": (meta.get("ownership", {}).get("name") if isinstance(meta.get("ownership"), dict) else str(meta.get("ownership") or "")),
                                "Employee Count": meta.get("employeeCount") or "",
                                "About Summary": (about.get("description") or header.get("about") or "")[:200] + "...",
                            }
                        except Exception:
                            pass

                    if not extracted_data.get("Official Website"):
                        web_m = re.search(r'"website"\s*:\s*"(https?://[^"]+)"', html_text)
                        if web_m:
                            extracted_data["Official Website"] = web_m.group(1).replace("\\/", "").strip()

                    if extracted_data.get("Official Website"):
                        break

                await asyncio.sleep(0.1)

        except Exception as exc:
            print(f"[!] Error during extraction: {exc}")

        await browser.close()

    elapsed = time.time() - start_time

    print("\n" + "-" * 70)
    print(f"EXTRACTED AMBITIONBOX COMPANY DATA (Completed in {elapsed:.2f}s):")
    print("-" * 70)
    if extracted_data:
        for k, v in extracted_data.items():
            if v:
                print(f"  * {k:<20}: {v}")
    else:
        print("  [!] No structured data could be extracted.")
    print("-" * 70 + "\n")

    return extracted_data


def main():
    parser = argparse.ArgumentParser(description="Test AmbitionBox company extraction")
    parser.add_argument(
        "--url",
        default="https://www.ambitionbox.com/overview/tcs-overview",
        help="AmbitionBox overview or review URL",
    )
    args = parser.parse_args()

    clean_url = args.url.strip()
    if "/reviews/" in clean_url:
        clean_url = re.sub(r"/reviews/([a-zA-Z0-9_-]+)-reviews", r"/overview/\1-overview", clean_url.split("?")[0])

    asyncio.run(test_ambitionbox_url(clean_url))


if __name__ == "__main__":
    main()
