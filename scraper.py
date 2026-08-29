import asyncio
from playwright.async_api import async_playwright
import pandas as pd
from datetime import datetime
import os

async def scrape_naukri():
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Target URL
        keyword = "python-developer"
        location = "bangalore"
        search_url = f"https://www.naukri.com/{keyword}-jobs-in-{location}"
        
        print(f"Navigating to {search_url}...")
        await page.goto(search_url, wait_until="networkidle")

        # Wait for job cards to load
        await page.wait_for_selector(".srp-jobtuple-wrapper", timeout=20000)

        # Scrape job details
        jobs = []
        job_cards = await page.query_selector_all(".srp-jobtuple-wrapper")

        for card in job_cards:
            try:
                title = await card.query_selector("a.title")
                company = await card.query_selector("a.comp-name")
                # Experience is often in a specific span or class
                exp = await card.query_selector(".expwdth")
                url = await title.get_attribute("href")

                jobs.append({
                    "title": await title.inner_text() if title else "N/A",
                    "company": await company.inner_text() if company else "N/A",
                    "experience": await exp.inner_text() if exp else "N/A",
                    "url": url,
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            except Exception as e:
                print(f"Skipping a card due to error: {e}")

        await browser.close()

        # Save to CSV
        if jobs:
            df = pd.DataFrame(jobs)
            filename = "naukri_jobs.csv"
            if os.path.exists(filename):
                existing_df = pd.read_csv(filename)
                df = pd.concat([existing_df, df]).drop_duplicates(subset=['url'], keep='first')
            
            df.to_csv(filename, index=False)
            print(f"Successfully scraped {len(jobs)} jobs.")
        else:
            print("No jobs found. The site structure might have changed.")

if __name__ == "__main__":
    asyncio.run(scrape_naukri())
