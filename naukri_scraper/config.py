"""Configuration settings and constants for the Naukri Scraper."""

from __future__ import annotations

NAUKRI_BASE_URL = "https://www.naukri.com"
NAUKRI_SITEMAP_INDEX_URL = f"{NAUKRI_BASE_URL}/sitemap.xml"
NAUKRI_INCREMENTAL_SITEMAP_URL = f"{NAUKRI_BASE_URL}/sitemap/incremental-jd-pages.xml"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Major Indian tech hubs, regions, and districts recognized in Naukri URLs
KNOWN_CITIES = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "bangalore-rural": "Bengaluru Rural",
    "bengaluru-rural": "Bengaluru Rural",
    "bangalore-urban": "Bengaluru Urban",
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "pune": "Pune",
    "mumbai": "Mumbai",
    "navi-mumbai": "Navi Mumbai",
    "mumbai-suburban": "Mumbai Suburban",
    "thane": "Thane",
    "delhi": "Delhi",
    "new-delhi": "Delhi",
    "delhi-ncr": "Delhi NCR",
    "ncr": "Delhi NCR",
    "noida": "Noida",
    "greater-noida": "Greater Noida",
    "gurugram": "Gurugram",
    "gurgaon": "Gurugram",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "chandigarh": "Chandigarh",
    "mohali": "Mohali",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "trivandrum": "Trivandrum",
    "thiruvananthapuram": "Trivandrum",
    "coimbatore": "Coimbatore",
    "indore": "Indore",
    "bhopal": "Bhopal",
    "lucknow": "Lucknow",
    "nagpur": "Nagpur",
    "bhubaneswar": "Bhubaneswar",
    "visakhapatnam": "Visakhapatnam",
    "vizag": "Visakhapatnam",
    "vadodara": "Vadodara",
    "surat": "Surat",
    "goa": "Goa",
    "kannur": "Kannur",
    "calicut": "Kozhikode",
    "kozhikode": "Kozhikode",
    "mysore": "Mysuru",
    "mysuru": "Mysuru",
    "remote": "Remote",
    "anywhere": "Remote",
    "work-from-home": "Remote",
}

# City to sitemap mapping when filtering specifically by city
CITY_SITEMAP_MAP = {
    "bangalore": "jobDescPagesBangalore.xml",
    "bengaluru": "jobDescPagesBangalore.xml",
    "pune": "jobDescPagesPune-1.xml.gz",
    "hyderabad": "jobDescPagesHyderabad-1.xml.gz",
    "mumbai": "jobDescPagesMumbai-1.xml.gz",
    "delhi": "jobDescPagesDelhi.xml",
    "noida": "jobDescPagesNoida.xml",
    "chennai": "jobDescPagesChennai.xml",
    "kolkata": "jobDescPagesKolkata.xml",
    "ahmedabad": "jobDescPagesAhmedabad.xml",
}

JOB_FIELDS = [
    "job_id",
    "title",
    "company",
    "company_website",
    "location",
    "experience_text",
    "salary",
    "skills",
    "job_description",
    "company_rating",
    "company_reviews_count",
    "ambition_box_url",
    "vacancies",
    "freshness",
    "posted_date",
    "min_experience",
    "max_experience",
    "url",
    "source",
]

COMPANY_FIELDS = [
    "company_name",
    "company_website",
    "total_jobs_posted",
    "job_titles",
    "naukri_job_urls",
    "locations",
    "experience_required",
    "top_skills",
    "salaries_disclosed",
    "company_rating",
    "company_reviews_count",
    "ambition_box_url",
    "latest_posted_date",
]
