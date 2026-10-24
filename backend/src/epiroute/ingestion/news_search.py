"""Find official outbreak pages. News text is never a case count.

TinyFish Search is limited to health-agency and wire domains. A hit is a URL
to fetch from that publisher. The number that enters the model still has to
be grounded in the official page.
"""

from __future__ import annotations

import logging

from epiroute.tinyfish.client import TinyFishClient, TinyFishNotConfiguredError

logger = logging.getLogger(__name__)

OFFICIAL_DOMAINS = "who.int,ecdc.europa.eu,paho.org,africacdc.org,cdc.gov,gov.uk"


def discover_report_urls(disease: str) -> list[str]:
    """Return official URLs mentioning ``disease``. Empty when TinyFish is off."""
    try:
        client = TinyFishClient()
    except TinyFishNotConfiguredError:
        logger.info("news discovery skipped; TinyFish is not configured")
        return []
    response = client.search(
        f"{disease} outbreak confirmed cases",
        include_domains=OFFICIAL_DOMAINS.split(","),
    )
    urls: list[str] = []
    for item in getattr(response, "results", []) or []:
        url = getattr(item, "url", None)
        if isinstance(url, str) and url not in urls:
            urls.append(url)
    return urls
