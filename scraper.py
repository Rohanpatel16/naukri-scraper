import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
except ImportError:
    # Fallback for different versions of the library
    from playwright_stealth import stealth_async as stealth_async
from datetime import datetime

async def scrape_naukri():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Realistic User Agent
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        
        # Apply Stealth to hide Playwright/Automation signatures
        await stealth_async(page)

        # Updated URL structure for better results
        url = "https://www.naukri.com/python-developer-jobs-in-bangalore"
        
        print(f"Navigating to {url}...")
        
        try:
            # Step 1: Visit home to establish cookies
            await page.goto("https://www.naukri.com/", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(1, 3))
            
            # Step 2: Visit the search page
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(random.uniform(3, 5))

            # Step 3: Extract internal JSON state (from your Apify findings)
            # This is window.__INITIAL_STATE__ for Naukri
            raw_data = await page.evaluate("() => window.__INITIAL_STATE__")
            
            job_list = []
            if raw_data:
                # Logic to drill into the Naukri JSON response structure
                try:
                    # Search pages store jobs here
                    details = raw_data.get('answer', {}).get('details', {})
                    bulk_data = details.get('jobDetails', [])
                    
                    for job in bulk_data:
                        job_list.append({
                            "title": job.get('title'),
                            "company": job.get('companyName'),
                            "location": job.get('placeholders', [{}])[0].get('label'),
                            "experience": job.get('placeholders', [{}, {}])[1].get('label'),
                            "url": f"https://www.naukri.com{job.get('jdURL')}",
                            "date": datetime.now().strftime("%Y-%m-%d")
                        })
                except Exception as e:
                    print(f"JSON Structure error: {e}")
            
            # Step 4: Final extraction check
            if job_list:
                df = pd.DataFrame(job_list)
                df.to_csv("naukri_data.csv", index=False)
                print(f"Success! Captured {len(job_list)} jobs.")
            else:
                # Save screenshot if blocked/empty
                await page.screenshot(path="error_screen.png")
                print("No jobs found. Check error_screen.png artifact.")

        except Exception as e:
            print(f"Scraper crashed: {e}")
            await page.screenshot(path="error_screen.png")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_naukri())
