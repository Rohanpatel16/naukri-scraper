import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright
# Use this exact import style for playwright-stealth
from playwright_stealth import stealth_async
from datetime import datetime

async def scrape_naukri():
    async with async_playwright() as p:
        # We use 'chrome' instead of 'chromium' because it's harder to detect
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Apply stealth
        await stealth_async(page)

        url = "https://www.naukri.com/python-developer-jobs-in-bangalore"
        print(f"Navigating to {url}...")
        
        try:
            # Establishing a session
            await page.goto("https://www.naukri.com/", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(2, 4))
            
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # The Apify Logic: Extract window.__INITIAL_STATE__
            raw_data = await page.evaluate("() => window.__INITIAL_STATE__")
            
            job_list = []
            if raw_data:
                try:
                    # Target the jobDetails inside the state
                    details = raw_data.get('answer', {}).get('details', {})
                    bulk_data = details.get('jobDetails', [])
                    for job in bulk_data:
                        job_list.append({
                            "title": job.get('title'),
                            "company": job.get('companyName'),
                            "url": f"https://www.naukri.com{job.get('jdURL')}",
                            "scraped_at": datetime.now().strftime("%Y-%m-%d")
                        })
                except:
                    pass

            if job_list:
                pd.DataFrame(job_list).to_csv("naukri_data.csv", index=False)
                print(f"Done! Found {len(job_list)} jobs.")
            else:
                await page.screenshot(path="error_screen.png")
                print("Blocked or page structure changed. Screenshot saved.")

        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="error_screen.png")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_naukri())
