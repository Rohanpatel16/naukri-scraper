import httpx
import json
import pandas as pd
from datetime import datetime
import os

# Configuration
QUERY = "python developer"
LOCATION = "bangalore"
FILENAME = "naukri_jobs.csv"

def scrape_naukri():
    url = "https://www.naukri.com/jobapi/v3/search"
    
    # These headers are critical to bypass basic bot detection
    headers = {
        "appid": "109",
        "systemid": "Naukri",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
    }
    
    params = {
        "noOfResults": "20",
        "urlType": "search_by_key_loc",
        "searchType": "adv",
        "keyword": QUERY,
        "location": LOCATION,
        "pageNo": "1",
        "experience": "0"  # 0 for freshers
    }

    try:
        response = httpx.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        jobs = []
        for job in data.get('jobDetails', []):
            jobs.append({
                "title": job.get('title'),
                "company": job.get('companyName'),
                "location": job.get('placeholders', [{}])[0].get('label'),
                "experience": job.get('placeholders', [{}, {}])[1].get('label'),
                "posted": job.get('footerPlaceholderLabel'),
                "url": f"https://www.naukri.com{job.get('jdURL')}",
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        
        df = pd.DataFrame(jobs)
        
        # Append to existing file or create new
        if os.path.exists(FILENAME):
            existing_df = pd.read_csv(FILENAME)
            df = pd.concat([existing_df, df]).drop_duplicates(subset=['url'], keep='first')
        
        df.to_csv(FILENAME, index=False)
        print(f"Successfully scraped {len(jobs)} jobs.")

    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    scrape_naukri()
