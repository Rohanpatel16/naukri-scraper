import asyncio
import json
import pandas as pd
from playwright.async_api import async_playwright
from datetime import datetime

async def scrape_naukri():
    async with async_playwright() as p:
        # Launching with a real user agent to bypass basic blocks
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Target URL (Example: Python Jobs in Bangalore)
        url = "https://www.naukri.com/python-developer-jobs-in-bangalore"
        
        print(f"Loading {url}...")
        await page.goto(url, wait_until="domcontentloaded")

        # 1. Wait for the H1 or splash screen to clear (Logic from your Apify script)
        try:
            await page.wait_for_selector('h1', timeout=30000)
        except Exception:
            print("Timed out or blocked by splash screen")
            await browser.close()
            return

        # 2. Extract data from window.__INITIAL_STATE__ (The "Goldmine" logic)
        raw_data = await page.evaluate("() => window.__INITIAL_STATE__")
        
        if not raw_data:
            print("Could not find __INITIAL_STATE__. Site might have blocked us.")
            await browser.close()
            return

        # 3. Parse the JSON (The Apify script logic)
        # In Naukri's search page, jobs are usually under 'groups' or 'jobDetails'
        job_list = []
        try:
            # This path changes slightly based on the page type (Search vs Company)
            # For Search Pages:
            bulk_data = raw_data.get('answer', {}).get('details', {}).get('jobDetails', [])
            
            for job in bulk_data:
                job_list.append({
                    "jobId": job.get('jobId'),
                    "title": job.get('title'),
                    "company": job.get('companyName'),
                    "location": job.get('placeholders', [{}])[0].get('label'),
                    "experience": job.get('placeholders', [{}, {}])[1].get('label'),
                    "salary": job.get('placeholders', [{}, {}, {}])[2].get('label'),
                    "tags": ", ".join(job.get('tagsAndSkills', [])),
                    "url": f"https://www.naukri.com{job.get('jdURL')}",
                    "scraped_at": datetime.now().isoformat()
                })
        except Exception as e:
            print(f"Error parsing JSON: {e}")

        # 4. Save to CSV
        if job_list:
            df = pd.DataFrame(job_list)
            df.to_csv("naukri_data.csv", index=False)
            print(f"Successfully extracted {len(job_list)} jobs.")
        else:
            print("No jobs found in the JSON state.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_naukri())
