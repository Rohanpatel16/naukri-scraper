# Naukri.com Fast Job Scraper

A fast, lightweight, anti-bot resilient scraper specifically built for [Naukri.com](https://www.naukri.com).

## Key Features

- **No Anti-Bot Blocks**: Streams Naukri's official public XML/Gzip sitemaps (including real-time incremental feeds) to discover live job listings without getting blocked by Cloudflare or reCAPTCHA.
- **Fast Execution**: Can process and filter through 25,000+ job listings in seconds.
- **Rich Metadata Extraction**: Parses Job Title, Company, Location, Min/Max Experience, and direct apply URLs.
- **Precise Filtering**:
  - **Keywords**: Filter by title / technology (e.g. `python`, `devops`, `aws`, `react`).
  - **Location**: Filter by Indian tech hubs (Bangalore, Pune, Hyderabad, Mumbai, Delhi/NCR, Remote, etc.).
  - **Experience**: Filter listings matching your target years of experience.
- **Multiple Formats**: Export directly to `.csv` or `.json`.
- **GitHub Actions Ready**: Automated daily runs via Cron and manual triggers with downloadable CSV artifacts.

---

## Installation

```bash
pip install -r naukri_scraper/requirements.txt
```

---

## Local Usage

Run the CLI from the project root:

### 1. Basic Search
```bash
python -m naukri_scraper.cli --keywords python devops
```

### 2. Scrape from a Custom Filter Search URL (Engineering/IT 24h)
```bash
python -m naukri_scraper.cli --url "https://www.naukri.com/jobs-in-india?functionAreaIdGid=4&functionAreaIdGid=5&functionAreaIdGid=8&jobAge=1&clusters=functionalAreaGid,Freshness" --pages 5 --output it_fresh_jobs.csv
```

### 3. Filter by Location and Experience
```bash
python -m naukri_scraper.cli --keywords "python" "django" --location "Bangalore" --experience 3 --max-jobs 50 --output bangalore_python_jobs.csv
```

### 4. Filter by Last 24 Hours / Time Limit
```bash
python -m naukri_scraper.cli --keywords "python" "devops" --hours 24 --output fresh_jobs_24h.csv
```

---

## Command-Line Options

| Option | Shorthand | Description | Default |
| :--- | :--- | :--- | :--- |
| `--url` | `-u` | Direct custom Naukri search URL to scrape | None |
| `--pages` | `-p` | Maximum pages to paginate through when using `--url` | `5` |
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

## Python API Usage

You can also import and use the scraper in your own Python scripts:

```python
from naukri_scraper import NaukriScraper, save_to_csv

scraper = NaukriScraper()
jobs = scraper.scrape(
    keywords=["python", "fastapi"],
    location="Hyderabad",
    experience=2,
    max_jobs=25
)

# Save to CSV
save_to_csv(jobs, "hyderabad_fastapi_jobs.csv")

for job in jobs[:5]:
    print(f"{job['title']} | {job['location']} | {job['experience_text']}")
    print(f"Apply: {job['url']}\n")
```

---

## Running in GitHub Actions

The workflow file is located at `.github/workflows/naukri_scraper.yml`.

1. Push this repository to GitHub.
2. Go to **Actions** tab in your repository.
3. Select **Naukri Job Scraper** and click **Run workflow**.
4. Set your search keywords, location, or experience level.
5. Once completed, download the generated `naukri-jobs-csv` artifact from the run summary.
