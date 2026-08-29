# Naukri.com Fast Job Scraper

A high-performance, anti-bot resilient job scraper for [Naukri.com](https://www.naukri.com) with built-in 24-hour time filtering, custom search URL support, and GitHub Actions automation.

---

## 🚀 Key Features

- **Anti-Bot Resilient**: Streams Naukri's official public XML/Gzip sitemaps (including real-time incremental feeds) to discover live job listings without getting blocked by Cloudflare or reCAPTCHA.
- **Custom Search URL Scraping**: Uses Playwright to scrape any custom filtered search URL (e.g. `jobs-in-india?functionAreaIdGid=4...`) across multiple pages.
- **24-Hour / Freshness Filter**: Filter jobs posted strictly in the last 24 hours (`--hours 24`) or last N days (`--days 1`).
- **Rich Metadata Extraction**: Parses Job Title, Company, Location, Min/Max Experience, Posting Date, and direct application URLs.
- **Multi-City & Technology Filtering**: Target specific tech hubs (Bangalore, Pune, Hyderabad, Mumbai, Delhi/NCR, Remote, etc.) and skills (Python, DevOps, React, Data Engineer, etc.).
- **Multiple Formats**: Export directly to `.csv` or `.json`.
- **GitHub Actions Ready**: Automated daily cron workflow (`06:00 UTC / 11:30 AM IST`) and manual workflow dispatch with downloadable CSV artifacts.

---

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/Rohanpatel16/naukri-scraper.git
cd naukri-scraper

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browser dependencies (for custom search URLs)
playwright install chromium
```

---

## 💻 Usage

### 1. Basic Keyword Search
```bash
python scraper.py --keywords python devops
```

### 2. Scrape from a Custom Search URL (e.g. Engineering/IT in last 24h)
```bash
python scraper.py --url "https://www.naukri.com/jobs-in-india?functionAreaIdGid=4&functionAreaIdGid=5&functionAreaIdGid=8&jobAge=1&clusters=functionalAreaGid,Freshness" --pages 5 --output fresh_tech_jobs.csv
```

### 3. Filter by Location, Experience, and Last 24 Hours
```bash
python scraper.py --keywords "python" "fastapi" --location "Bangalore" --experience 3 --hours 24 --max-jobs 50 --output bangalore_24h.csv
```

### 4. Export to JSON
```bash
python scraper.py --keywords "data engineer" --days 3 --output data_jobs.json
```

---

## ⚙️ Command-Line Options

| Option | Shorthand | Description | Default |
| :--- | :--- | :--- | :--- |
| `--url` | `-u` | Direct custom Naukri search URL to scrape | None |
| `--pages` | `-p` | Maximum pages to paginate when using `--url` | `5` |
| `--keywords` | `-k` | One or more keywords to search for | `python` |
| `--location` | `-l` | City or region filter (e.g., `Bangalore`, `Pune`, `Remote`) | All |
| `--experience` | `-e` | Candidate experience in years (e.g., `3`) | Any |
| `--hours` | `-H` | Only include jobs posted in last N hours (e.g. `24`) | All time |
| `--days` | `-D` | Only include jobs posted in last N days (e.g. `1`, `3`, `7`) | All time |
| `--max-jobs` | `-n` | Maximum number of matched jobs to collect | `50` |
| `--max-sitemaps` | `-s` | Number of sitemaps to scan | `5` |
| `--output` | `-o` | Output file path (`.csv` or `.json`) | `naukri_jobs.csv` |
| `--verbose` | `-v` | Enable detailed debug output | `False` |

---

## 🐍 Python API Usage

```python
# Method A: Fast Sitemap Scraper (no browser required)
from naukri_scraper import NaukriScraper, save_to_csv

scraper = NaukriScraper()
jobs = scraper.scrape(
    keywords=["python", "devops"],
    location="Bangalore",
    experience=3,
    hours=24,
    max_jobs=50
)
save_to_csv(jobs, "naukri_jobs.csv")

# Method B: Browser Scraper for Custom Filter URLs
from naukri_scraper import NaukriBrowserScraper

browser_scraper = NaukriBrowserScraper()
custom_jobs = browser_scraper.scrape_url(
    search_url="https://www.naukri.com/jobs-in-india?functionAreaIdGid=4&functionAreaIdGid=5&functionAreaIdGid=8&jobAge=1&clusters=functionalAreaGid,Freshness",
    max_pages=5,
    max_jobs=100
)
save_to_csv(custom_jobs, "custom_jobs.csv")
```

---

## 🤖 GitHub Actions Setup

The automated workflow is located in `.github/workflows/naukri_scraper.yml`.

1. **Daily Runs**: Automatically runs every day at **06:00 UTC (11:30 AM IST)**.
2. **Manual Dispatch**: Trigger anytime from the **Actions** tab on GitHub:
   - Provide custom keywords OR paste any custom search URL.
   - Set location, experience, or time limits.
3. **Artifacts**: Download the generated `naukri-jobs-csv` directly from the GitHub Actions run summary.

---

## 📄 License
MIT License