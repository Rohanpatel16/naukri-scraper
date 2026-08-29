"""URL and Metadata Parser for Naukri job listings."""

import datetime
import re
from typing import Any, Dict, List, Optional

from .config import KNOWN_CITIES


# Common company suffix keywords to help identify company boundaries
COMPANY_SUFFIXES = {
    "ltd", "limited", "pvt", "private", "inc", "corp", "corporation",
    "technologies", "technology", "tech", "solutions", "services", "consulting",
    "systems", "infotech", "labs", "software", "global", "india"
}


def parse_job_url(url: str) -> Optional[Dict[str, Any]]:
    """Parse a Naukri job listing URL into a structured job record.

    Example URL:
        https://www.naukri.com/job-listings-oracle-fusion-cpq-techno-functional-consultant-hiresquad-hyderabad-chennai-bengaluru-6-to-11-years-250826021510

    Returns:
        Dict containing job_id, title, company, location, min_experience,
        max_experience, experience_text, posted_date, url, and source.
    """
    if not url or "job-listings-" not in url:
        return None

    # Extract slug and job_id
    match = re.search(r"/job-listings-(.+)-(\d+)$", url.strip())
    if not match:
        return None

    raw_slug = match.group(1)
    job_id = match.group(2)

    # 1. Extract Experience range
    exp_match = re.search(r"-(\d+)(?:-to-(\d+))?-years(?:-|$)", raw_slug)
    min_exp, max_exp = 0, 99
    exp_text = "Not specified"

    if exp_match:
        min_exp = int(exp_match.group(1))
        max_exp = int(exp_match.group(2)) if exp_match.group(2) is not None else min_exp
        exp_text = f"{min_exp}-{max_exp} yrs" if min_exp != max_exp else f"{min_exp} yrs"
        slug_without_exp = raw_slug[: exp_match.start()]
    else:
        slug_without_exp = raw_slug

    # 2. Extract Posting Date from Job ID prefix (DDMMYY format)
    posted_date_str = ""
    posted_date_obj: Optional[datetime.date] = None
    if len(job_id) >= 6:
        d_str, m_str, y_str = job_id[0:2], job_id[2:4], job_id[4:6]
        try:
            day, month, year = int(d_str), int(m_str), int("20" + y_str)
            posted_date_obj = datetime.date(year, month, day)
            posted_date_str = posted_date_obj.isoformat()
        except ValueError:
            pass

    # 3. Extract Locations by matching known city tokens from the right end of slug
    tokens = slug_without_exp.split("-")
    detected_locations: List[str] = []

    i = len(tokens)
    while i > 0:
        if i >= 2:
            two_word = f"{tokens[i-2]}-{tokens[i-1]}".lower()
            if two_word in KNOWN_CITIES:
                detected_locations.insert(0, KNOWN_CITIES[two_word])
                tokens = tokens[: i - 2]
                i -= 2
                continue

        single_word = tokens[i - 1].lower()
        if single_word in KNOWN_CITIES:
            detected_locations.insert(0, KNOWN_CITIES[single_word])
            tokens = tokens[: i - 1]
            i -= 1
            continue

        break

    location_str = ", ".join(detected_locations) if detected_locations else "India / Unspecified"

    # 4. Clean and parse Title and Company
    remaining_text = " ".join(tokens).title().strip()
    if not remaining_text:
        return None

    # Heuristic company detection from right side if suffixes exist
    title = remaining_text
    company = ""

    tokens_lower = [t.lower() for t in tokens]
    suffix_indices = [idx for idx, t in enumerate(tokens_lower) if t in COMPANY_SUFFIXES]

    if suffix_indices:
        start_company_idx = max(0, suffix_indices[0] - 1)
        if start_company_idx >= 2:
            title = " ".join(tokens[:start_company_idx]).title()
            company = " ".join(tokens[start_company_idx:]).title()

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location_str,
        "min_experience": min_exp,
        "max_experience": max_exp,
        "experience_text": exp_text,
        "posted_date": posted_date_str,
        "_posted_date_obj": posted_date_obj,
        "url": url.strip(),
        "source": "naukri",
    }


def matches_filters(
    job: Dict[str, Any],
    keywords: Optional[List[str]] = None,
    location_filter: Optional[str] = None,
    experience_filter: Optional[int] = None,
    since_date: Optional[datetime.date] = None,
) -> bool:
    """Check if a parsed job satisfies the given search filters."""
    # 1. Keyword filter
    if keywords:
        search_haystack = f"{job['title']} {job['company']} {job['url']}".lower()
        has_match = any(kw.lower() in search_haystack for kw in keywords if kw.strip())
        if not has_match:
            return False

    # 2. Location filter
    if location_filter:
        loc_haystack = f"{job['location']} {job['url']}".lower()
        if location_filter.lower() not in loc_haystack:
            return False

    # 3. Experience filter (candidate's years of exp must fall inside job's range)
    if experience_filter is not None:
        if not (job["min_experience"] <= experience_filter <= job["max_experience"]):
            return False

    # 4. Time limit filter (e.g. posted on or after since_date)
    if since_date is not None:
        job_date = job.get("_posted_date_obj")
        if job_date is not None and job_date < since_date:
            return False

    return True

