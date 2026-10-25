"""ECDC Communicable Disease Threats Report as a second case-count source.

TinyFish Fetch reads the weekly PDF when a key is configured. The returned
text goes through the same sentence parser as a WHO page. Counts from this
source are stored under ``ecdc_cdtr`` and compared with WHO; they are never
differenced against a WHO total.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from endemica.core.clock import utc_now
from endemica.ingestion.parser import parse_report
from endemica.tinyfish.client import TinyFishClient, TinyFishNotConfiguredError

logger = logging.getLogger(__name__)

SOURCE_NAME = "ecdc_cdtr"
LANDING_URL = "https://www.ecdc.europa.eu/en/publications-data/communicable-disease-threats-report"
PDF_TEMPLATE = (
    "https://www.ecdc.europa.eu/sites/default/files/documents/"
    "communicable-disease-threats-report-week-{week}-{year}.pdf"
)
_PDF_HREF = re.compile(r"communicable-disease-threats-report-week-(\d+)-(\d{4})\.pdf", re.I)


def candidate_pdf_urls(text: str, *, year: int | None = None, week: int | None = None) -> list[str]:
    """PDF links found in a landing page, plus the conventional URL when given."""
    found = [
        f"https://www.ecdc.europa.eu/sites/default/files/documents/{match.group(0)}"
        for match in _PDF_HREF.finditer(text)
    ]
    if year is not None and week is not None:
        found.append(PDF_TEMPLATE.format(week=week, year=year))
    unique: list[str] = []
    for url in found:
        if url not in unique:
            unique.append(url)
    return unique


def fetch_text(url: str) -> str | None:
    """Read a report URL through TinyFish. Returns None when it is not configured."""
    try:
        client = TinyFishClient()
    except TinyFishNotConfiguredError:
        logger.info("ecdc fetch skipped; TinyFish is not configured")
        return None
    response = client.fetch([url])
    for page in getattr(response, "results", []) or []:
        text = getattr(page, "text", None) or getattr(page, "markdown", None)
        if isinstance(text, str) and text.strip():
            return text
    return None


def extract_counts(
    text: str, *, title: str, published_at: datetime | None = None
) -> list[dict[str, object]]:
    """Grounded-style count rows. The caller stores them; this function does not."""
    extracted = parse_report(text, title=title)
    published = published_at or utc_now()
    rows: list[dict[str, object]] = []
    for location in extracted.locations:
        if location.cases_confirmed is None and location.deaths is None:
            continue
        rows.append(
            {
                "source_name": SOURCE_NAME,
                "country_iso3": location.country,
                "cases_confirmed": location.cases_confirmed,
                "deaths": location.deaths,
                "evidence_text": location.evidence,
                "published_at": published,
                "disease_label": extracted.disease,
            }
        )
    return rows
