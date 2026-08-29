"""Ultra-Fast CLI diagnostic tool to test AmbitionBox company data and website extraction.

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
    """Test extracting company metadata and official website from AmbitionBox URL in 1-2 seconds."""
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

        # Aggressively block non-essential trackers, fonts, images, and styles
        async def route_handler(route):
            url_str = route.request.url.lower()
            rtype = route.request.resource_type
            if rtype in ["image", "media", "font", "stylesheet"] or any(
                x in url_str for x in ["google", "clarity", "facebook", "doubleclick", "analytics", "track", "hotjar"]
            ):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)

        t_nav = time.time()
        print("[*] Navigating with fast commit stream...")
        try:
            await page.goto(url, wait_until="commit", timeout=12000)

            # Poll for __NEXT_DATA__ JSON payload immediately as HTML streams
            for _ in range(40):
                data = await page.evaluate("""() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (el) {
                        try {
                            const d = JSON.parse(el.textContent);
                            const props = d.props?.pageProps || {};
                            const meta = props.companyMetaInformation || {};
                            const header = props.companyHeaderData || {};
                            const about = props.companyAbout || {};
                            return {
                                name: header.name || header.companyName || '',
                                website: meta.website || header.website || '',
                                rating: String(header.rating || header.companyRating || ''),
                                reviews: String(header.reviewsCount || header.totalReviews || ''),
                                industry: meta.industry || header.industry || '',
                                headquarters: meta.headquarters || header.hq || '',
                                ownership: (meta.ownership && meta.ownership.name) ? meta.ownership.name : String(meta.ownership || ''),
                                employees: meta.employeeCount || '',
                                about: (about.description || header.about || '').slice(0, 200),
                            };
                        } catch(e) {}
                    }
                    return null;
                }""")
                if data and data.get("website"):
                    extracted_data = {
                        "Company Name": data.get("name"),
                        "Official Website": data.get("website"),
                        "Rating": data.get("rating"),
                        "Reviews Count": data.get("reviews"),
                        "Industry": data.get("industry"),
                        "Headquarters": data.get("headquarters"),
                        "Ownership / Type": data.get("ownership"),
                        "Employee Count": data.get("employees"),
                        "About Summary": data.get("about") + ("..." if data.get("about") else ""),
                    }
                    break
                await asyncio.sleep(0.05)

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
