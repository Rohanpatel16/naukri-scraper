from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .config import COMPANY_FIELDS, JOB_FIELDS

logger = logging.getLogger(__name__)


def aggregate_companies(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate individual job listings into unique company summary records."""
    comp_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "company_name": "",
        "company_website": "",
        "total_jobs_posted": 0,
        "job_titles": [],
        "naukri_job_urls": [],
        "locations": set(),
        "experience_required": set(),
        "top_skills": set(),
        "salaries": set(),
        "company_rating": "",
        "company_reviews_count": "",
        "ambition_box_url": "",
        "latest_posted_date": "",
    })

    for job in jobs:
        cname = (job.get("company") or "").strip()
        if not cname:
            continue

        c = comp_map[cname]
        c["company_name"] = cname
        if job.get("company_website") and not c["company_website"]:
            c["company_website"] = job["company_website"].strip()

        c["total_jobs_posted"] += 1

        title = (job.get("title") or "").strip()
        if title and title not in c["job_titles"]:
            c["job_titles"].append(title)

        url = (job.get("url") or "").strip()
        if url and url not in c["naukri_job_urls"]:
            c["naukri_job_urls"].append(url)

        loc = (job.get("location") or "").strip()
        if loc and loc != "Not specified":
            for single_loc in loc.split(","):
                clean_loc = single_loc.strip()
                if clean_loc:
                    c["locations"].add(clean_loc)

        exp = (job.get("experience_text") or "").strip()
        if exp and exp != "Not specified":
            c["experience_required"].add(exp)

        sal = (job.get("salary") or "").strip()
        if sal and sal not in ["Not disclosed", "Not Disclosed", ""]:
            c["salaries"].add(sal)

        raw_skills = job.get("skills") or ""
        if raw_skills:
            for s in raw_skills.split(","):
                clean_s = s.strip()
                if clean_s:
                    c["top_skills"].add(clean_s)

        if not c["company_rating"] and job.get("company_rating"):
            c["company_rating"] = job["company_rating"]
        if not c["company_reviews_count"] and job.get("company_reviews_count"):
            c["company_reviews_count"] = job["company_reviews_count"]
        if not c["ambition_box_url"] and job.get("ambition_box_url"):
            c["ambition_box_url"] = job["ambition_box_url"]

        p_date = job.get("posted_date") or ""
        if p_date and p_date > c["latest_posted_date"]:
            c["latest_posted_date"] = p_date

    # Flatten aggregated dicts for CSV export sorted by highest jobs posted
    sorted_comps = sorted(comp_map.values(), key=lambda x: x["total_jobs_posted"], reverse=True)
    result = []

    for c in sorted_comps:
        result.append({
            "company_name": c["company_name"],
            "company_website": c["company_website"],
            "total_jobs_posted": c["total_jobs_posted"],
            "job_titles": " | ".join(c["job_titles"]),
            "naukri_job_urls": " | ".join(c["naukri_job_urls"]),
            "locations": ", ".join(sorted(c["locations"])),
            "experience_required": ", ".join(sorted(c["experience_required"])),
            "top_skills": ", ".join(sorted(c["top_skills"])),
            "salaries_disclosed": ", ".join(sorted(c["salaries"])) if c["salaries"] else "Not disclosed",
            "company_rating": c["company_rating"],
            "company_reviews_count": c["company_reviews_count"],
            "ambition_box_url": c["ambition_box_url"],
            "latest_posted_date": c["latest_posted_date"],
        })

    return result


def save_to_csv(jobs: List[Dict[str, Any]], filename: str = "naukri_jobs.csv") -> Path:
    """Save a list of job dicts to a CSV file."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=JOB_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow(job)

    logger.info("Saved %d jobs to CSV: %s", len(jobs), path.resolve())
    return path


def save_companies_to_csv(companies: List[Dict[str, Any]], filename: str = "naukri_companies.csv") -> Path:
    """Save a list of aggregated company dicts to a CSV file."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPANY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for c in companies:
            writer.writerow(c)

    logger.info("Saved %d unique companies to CSV: %s", len(companies), path.resolve())
    return path


def save_to_json(jobs: List[Dict[str, Any]], filename: str = "naukri_jobs.json") -> Path:
    """Save a list of job dicts to a JSON file."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    logger.info("Saved %d jobs to JSON: %s", len(jobs), path.resolve())
    return path


def save_companies_to_json(companies: List[Dict[str, Any]], filename: str = "naukri_companies.json") -> Path:
    """Save a list of aggregated company dicts to a JSON file."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(companies, f, indent=2, ensure_ascii=False)

    logger.info("Saved %d unique companies to JSON: %s", len(companies), path.resolve())
    return path
