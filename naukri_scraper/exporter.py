"""Export utilities for saving scraped jobs to CSV or JSON formats."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from .config import JOB_FIELDS

logger = logging.getLogger(__name__)


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


def save_to_json(jobs: List[Dict[str, Any]], filename: str = "naukri_jobs.json") -> Path:
    """Save a list of job dicts to a JSON file."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    logger.info("Saved %d jobs to JSON: %s", len(jobs), path.resolve())
    return path
