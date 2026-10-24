from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from epiroute.core.clock import as_utc, utc_now
from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import ExternalServiceError
from epiroute.core.http import build_client, request_with_retry
from epiroute.epidemiology import diseases as disease_catalog
from epiroute.epidemiology.profiles import match_profile_key
from epiroute.ingestion.html_text import html_to_text, join_sections

logger = logging.getLogger(__name__)

SOURCE_NAME = "WHO Disease Outbreak News"
LICENSE_NOTE = "WHO terms of use: attribution required, commercial reuse restricted."
_SERVICE = "WHO DON API"
_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class DonRecord:
    source_identifier: str
    url_name: str
    title: str
    source_url: str
    published_at: datetime | None
    retrieved_at: datetime
    disease_label: str | None
    disease_key: str
    disease_name: str
    disease_family: str
    pathogen_key: str | None
    summary_text: str
    narrative_text: str
    content_sha256: str
    raw_fields: dict[str, Any]

    @property
    def has_narrative(self) -> bool:
        return bool(self.narrative_text.strip())


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def disease_label_from_title(title: str) -> str | None:
    return disease_catalog.extract_label(title)


def _identifier(item: dict[str, Any]) -> str | None:
    for key in ("DonId", "UrlName", "Id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_don_item(
    item: dict[str, Any], *, settings: Settings, retrieved_at: datetime
) -> DonRecord | None:
    identifier = _identifier(item)
    if identifier is None:
        return None

    url_name = str(item.get("UrlName") or identifier).strip()
    title = html_to_text(str(item.get("Title") or "")).strip()
    if not title:
        return None

    narrative = join_sections(
        item.get("Summary"),
        item.get("Overview"),
        item.get("Epidemiology"),
        item.get("Assessment"),
    )
    summary = html_to_text(str(item.get("Summary") or "")) or html_to_text(
        str(item.get("Overview") or "")
    )
    disease_key, disease_name, disease_family, label = disease_catalog.resolve(title)

    return DonRecord(
        source_identifier=identifier,
        url_name=url_name,
        title=title,
        source_url=settings.who_don_item_url_template.format(url_name=url_name),
        published_at=_parse_timestamp(item.get("PublicationDateAndTime"))
        or _parse_timestamp(item.get("PublicationDate")),
        retrieved_at=retrieved_at,
        disease_label=label,
        disease_key=disease_key,
        disease_name=disease_name,
        disease_family=disease_family,
        pathogen_key=match_profile_key(disease_name)
        or match_profile_key(label)
        or match_profile_key(title),
        summary_text=summary[:4000],
        narrative_text=narrative,
        content_sha256=hashlib.sha256(narrative.encode("utf-8")).hexdigest(),
        raw_fields={
            key: item.get(key)
            for key in ("DonId", "UrlName", "PublicationDate", "PublicationDateAndTime")
        },
    )


def fetch_don_page(
    *, skip: int = 0, top: int = _PAGE_SIZE, settings: Settings | None = None
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    params = {
        "$orderby": "PublicationDateAndTime desc",
        "$top": str(top),
        "$skip": str(skip),
    }
    with build_client(settings) as client:
        response = request_with_retry(
            client, "GET", settings.who_don_api_url, service=_SERVICE, params=params
        )
    if response.status_code != 200:
        msg = f"HTTP {response.status_code}"
        raise ExternalServiceError(_SERVICE, msg, status_code=response.status_code)
    payload = response.json()
    value = payload.get("value")
    return value if isinstance(value, list) else []


def iter_recent_records(
    *, limit: int | None = None, settings: Settings | None = None
) -> Iterator[DonRecord]:
    settings = settings or get_settings()
    cap = limit if limit is not None else settings.ingest_max_records
    retrieved_at = utc_now()
    produced = 0
    skip = 0

    while produced < cap:
        batch = fetch_don_page(skip=skip, top=min(_PAGE_SIZE, cap - produced), settings=settings)
        if not batch:
            return
        for item in batch:
            record = parse_don_item(item, settings=settings, retrieved_at=retrieved_at)
            if record is None:
                logger.warning("skipping unparseable DON item", extra={"keys": sorted(item)})
                continue
            yield record
            produced += 1
            if produced >= cap:
                return
        skip += len(batch)


def load_archive(
    path: Path, *, settings: Settings | None = None, limit: int | None = None
) -> list[DonRecord]:
    settings = settings or get_settings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("value") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    retrieved_at = utc_now()
    records: list[DonRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = parse_don_item(item, settings=settings, retrieved_at=retrieved_at)
        if record is not None:
            records.append(record)
        if limit is not None and len(records) >= limit:
            break
    records.sort(key=lambda r: r.published_at or utc_now(), reverse=True)
    return records


_ARCHIVE_PAGE_SIZE = 100


def fetch_full_archive(
    *,
    settings: Settings | None = None,
    page_size: int = _ARCHIVE_PAGE_SIZE,
    max_pages: int = 200,
) -> dict[str, Any]:
    settings = settings or get_settings()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    skip = 0

    with build_client(settings) as client:
        for _ in range(max_pages):
            params = {
                "$orderby": "PublicationDateAndTime desc",
                "$top": str(page_size),
                "$skip": str(skip),
            }
            response = request_with_retry(
                client, "GET", settings.who_don_api_url, service=_SERVICE, params=params
            )
            if response.status_code != 200:
                msg = f"HTTP {response.status_code}"
                raise ExternalServiceError(_SERVICE, msg, status_code=response.status_code)
            batch = response.json().get("value")
            if not isinstance(batch, list) or not batch:
                break

            fresh = 0
            for item in batch:
                if not isinstance(item, dict):
                    continue
                key = _identifier(item) or str(item.get("Id") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(item)
                fresh += 1

            skip += len(batch)
            if fresh == 0:
                break
            logger.info("fetched DON page", extra={"skip": skip, "items": len(items)})

    return {"source": settings.who_don_api_url, "retrieved_at": utc_now().isoformat(), "value": items}
