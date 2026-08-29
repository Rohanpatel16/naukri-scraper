import asyncio
import random
import pandas as pd
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from datetime import datetime

async def scrape_naukri():
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        
        # Add a realistic user agent
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = await context.new_page()
        
        # APPLY STEALTH
        await stealth_async(page)

        # Target URL
        url = "https://www.naukri.com/python-developer-jobs-in-bangalore"
        
        print(f"Navigating to {url}...")
        
        try:
            # Go to home page first to get cookies, then to the search page
            await page.goto("https://www.naukri.com/", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2, 5)) 
            
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(random.uniform(3, 6))

            # Try to extract the JSON state (the Apify logic)
            raw_data = await page.evaluate("() => window.__INITIAL_STATE__")
            
            job_list = []
            if raw_data:
                # Parsing logic from the internal state
                bulk_data = raw_data.get('answer', {}).get('details', {}).get('jobDetails', [])
                for job in bulk_data:
                    job_list.append({
                        "title": job.get('title'),
                        "company": job.get('companyName'),
                        "location": job.get('placeholders', [{}])[0].get('label'),
                        "url": f"https://www.naukri.com{job.get('jdURL')}",
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
            
            # Fallback: If JSON fails, try DOM scraping
            if not job_list:
                print("JSON state not found, trying DOM scraping...")
                job_cards = await page.query_selector_all(".srp-jobtuple-wrapper")
                for card in job_cards:
                    title_el = await card.query_selector("a.title")
                    if title_el:
                        job_list.append({
                            "title": await title_el.inner_text(),
                            "company": "N/A",
                            "url": await title_el.get_attribute("href"),
                            "date": datetime.now().strftime("%Y-%m-%d")
                        })

            if job_list:
                df = pd.DataFrame(job_list)
                df.to_csv("naukri_data.csv", index=False)
                print(f"Success! Saved {len(job_list)} jobs.")
            else:
                # Capture screenshot to see why it failed (will be in GitHub artifacts)
                await page.screenshot(path="error_screen.png")
                print("Failed to find jobs. Saved error_screen.png for debugging.")

        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_naukri())
