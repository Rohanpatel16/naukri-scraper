"""CLI diagnostic tool to test AmbitionBox company data and website extraction.

Can be run locally or via GitHub Actions workflow dispatch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any, Dict

from playwright.async_api import async_playwright

DEFAULT_TEST_URLS = [
    "https://www.ambitionbox.com/overview/tcs-overview",
    "https://www.ambitionbox.com/overview/infosys-overview",
    "https://www.ambitionbox.com/overview/cognizant-overview",
]


async def test_ambitionbox_url(url: str) -> Dict[str, Any]:
    """Test extracting company metadata and official website from AmbitionBox URL."""
    print("=" * 70)
    print(f"[*] Testing AmbitionBox URL : {url}")
    print("=" * 70)

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
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
            },
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        print("[*] 1. Testing Playwright in-browser API context.request.get()...")
        extracted_data: Dict[str, Any] = {}

        try:
            res = await context.request.get(url, timeout=12000)
            print(f"    [+] HTTP Status Code: {res.status}")
            text = await res.text()
            print(f"    [+] Response Length: {len(text):,} bytes")

            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text)
            if m:
                payload = json.loads(m.group(1))
                props = payload.get("props", {}).get("pageProps", {})
                header = props.get("companyHeaderData", {}) or {}
                meta = props.get("companyMetaInformation", {}) or {}
                about = props.get("companyAbout", {}) or {}

                extracted_data = {
                    "Company Name": header.get("name") or header.get("companyName") or "",
                    "Official Website": (meta.get("website") or header.get("website") or "").strip(),
                    "Rating": str(header.get("rating") or header.get("companyRating") or ""),
                    "Reviews Count": str(header.get("reviewsCount") or header.get("totalReviews") or ""),
                    "Industry": meta.get("industry") or header.get("industry") or "",
                    "Headquarters": meta.get("headquarters") or header.get("hq") or "",
                    "Ownership / Type": meta.get("ownership") or "",
                    "Employee Count": meta.get("employeeCount") or "",
                    "About Summary": (about.get("description") or header.get("about") or "")[:200] + "...",
                }
            else:
                web_m = re.search(r'"website"\s*:\s*"(https?://[^"]+)"', text)
                if web_m:
                    extracted_data["Official Website"] = web_m.group(1).replace("\\/", "").strip()

        except Exception as exc:
            print(f"    [!] Error during API fetch: {exc}")

        # If needed, test full page load fallback
        if not extracted_data.get("Official Website"):
            print("[*] 2. Fallback: Testing full page DOM render...")
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page_website = await page.evaluate("""() => {
                    try {
                        const el = document.getElementById('__NEXT_DATA__');
                        if (el) {
                            const d = JSON.parse(el.textContent);
                            const props = d.props?.pageProps;
                            return props?.companyMetaInformation?.website || props?.companyHeaderData?.website || '';
                        }
                    } catch(e) {}
                    return '';
                }""")
                if page_website:
                    extracted_data["Official Website"] = page_website
            except Exception as exc:
                print(f"    [!] Page render error: {exc}")
            await page.close()

        await browser.close()

    print("\n" + "-" * 70)
    print("EXTRACTED AMBITIONBOX COMPANY DATA:")
    print("-" * 70)
    if extracted_data:
        for k, v in extracted_data.items():
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

    # Automatically transform review URL to overview URL if given
    clean_url = args.url.strip()
    if "/reviews/" in clean_url:
        clean_url = re.sub(r"/reviews/([a-zA-Z0-9_-]+)-reviews", r"/overview/\1-overview", clean_url.split("?")[0])

    asyncio.run(test_ambitionbox_url(clean_url))


if __name__ == "__main__":
    main()
