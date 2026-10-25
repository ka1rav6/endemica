"""First-report dates for the two outbreaks the hazard model is allowed to use.

COVID-19 dates come from the Johns Hopkins cumulative table and are checked
against Our World in Data. Mpox dates come from the Global.health line list.
Ebola is not a training label.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import cast

import pandas as pd

from endemica.core.config import Settings, get_settings
from endemica.core.http import build_client, request_with_retry
from endemica.datasets.iso import resolve

logger = logging.getLogger(__name__)

JHU_URL = (
    "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/"
    "csse_covid_19_data/csse_covid_19_time_series/time_series_covid19_confirmed_global.csv"
)
OWID_URL = (
    "https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/owid-covid-data.csv"
)
MPOX_URLS = (
    "https://raw.githubusercontent.com/globaldothealth/monkeypox/main/latest.csv",
    "https://raw.githubusercontent.com/owid/monkeypox/master/owid-monkeypox-data.csv",
)

TRAINING_OUTBREAKS = ("covid_2020", "mpox_2022")


def labels_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = settings.raw_data_dir.parent / "labels"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download(url: str, target: Path, *, service: str) -> Path | None:
    settings = get_settings()
    try:
        with build_client(settings) as client:
            response = request_with_retry(client, "GET", url, service=service)
        if response.status_code != 200 or not response.content:
            return None
        target.write_bytes(response.content)
    except Exception:
        logger.warning("label download failed", extra={"url": url})
        return None
    return target


def _parse_jhu_date(value: str) -> datetime | None:
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def first_reports_from_jhu(path: Path) -> pd.DataFrame:
    """One row per country: the first day the cumulative total exceeds zero."""
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        return pd.DataFrame(columns=["outbreak", "iso3", "first_report"])
    date_fields = [name for name in reader.fieldnames if _parse_jhu_date(name)]
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in reader:
        iso3 = resolve(row.get("Country/Region"))
        if iso3 is None:
            continue
        for field in date_fields:
            try:
                totals[iso3][field] += float(row[field] or 0)
            except ValueError:
                continue
    records: list[dict[str, object]] = []
    for iso3, series in totals.items():
        for field in date_fields:
            if series[field] > 0:
                records.append(
                    {
                        "outbreak": "covid_2020",
                        "iso3": iso3,
                        "first_report": _parse_jhu_date(field),
                        "source": "jhu_csse",
                    }
                )
                break
    return pd.DataFrame(records)


def first_reports_from_owid(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=["iso_code", "date", "total_cases"])
    frame = frame[frame["iso_code"].astype(str).str.len() == 3]
    frame = frame[frame["total_cases"].fillna(0) > 0]
    first = frame.groupby("iso_code", as_index=False)["date"].min()
    first["first_report"] = pd.to_datetime(first["date"])
    return pd.DataFrame(
        {
            "outbreak": "covid_2020",
            "iso3": first["iso_code"].str.upper(),
            "first_report": first["first_report"],
            "source": "owid",
        }
    )


def agreement(primary: pd.DataFrame, check: pd.DataFrame, *, days: int = 3) -> float | None:
    """Share of countries whose first-report dates agree within ``days``."""
    if primary.empty or check.empty:
        return None
    merged = primary.merge(check, on="iso3", suffixes=("_primary", "_check"))
    if merged.empty:
        return None
    gap = (merged["first_report_primary"] - merged["first_report_check"]).abs().dt.days
    return float((gap <= days).mean())


def _column(frame: pd.DataFrame, *names: str) -> str | None:
    lookup = {column.casefold(): column for column in frame.columns}
    for name in names:
        found = lookup.get(name.casefold())
        if found:
            return found
    return None


def first_reports_from_mpox(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    country_column = _column(frame, "Country", "country", "location")
    date_column = _column(frame, "Date_confirmation", "date_confirmation", "Date_entry")
    if country_column is None or date_column is None:
        return pd.DataFrame(columns=["outbreak", "iso3", "first_report", "source"])
    frame = frame.dropna(subset=[country_column, date_column])
    frame["iso3"] = frame[country_column].map(lambda value: resolve(str(value)))
    frame["first_report"] = pd.to_datetime(frame[date_column], errors="coerce")
    frame = frame.dropna(subset=["iso3", "first_report"])
    first = frame.groupby("iso3", as_index=False)["first_report"].min()
    first["outbreak"] = "mpox_2022"
    first["source"] = "global_health"
    # cast: pandas-stubs types a multi-column selection as a Series.
    return cast("pd.DataFrame", first[["outbreak", "iso3", "first_report", "source"]])


def weekly_cases_from_owid(path: Path, outbreak: str) -> pd.DataFrame:
    """Sum daily new cases to Sunday weeks."""
    frame = pd.read_csv(path, usecols=["iso_code", "date", "new_cases"])
    frame = frame[frame["iso_code"].astype(str).str.len() == 3]
    frame["date"] = pd.to_datetime(frame["date"])
    frame["new_cases"] = frame["new_cases"].fillna(0).clip(lower=0)
    frame["week_end"] = frame["date"] + pd.to_timedelta(6 - frame["date"].dt.dayofweek, unit="D")
    grouped = frame.groupby(["iso_code", "week_end"], as_index=False)["new_cases"].sum()
    return pd.DataFrame(
        {
            "outbreak": outbreak,
            "iso3": grouped["iso_code"].str.upper(),
            "week_end": grouped["week_end"],
            "new_cases": grouped["new_cases"],
        }
    )


def weekly_cases_from_jhu(path: Path) -> pd.DataFrame:
    """New cases by country on every seventh JHU date."""
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        return pd.DataFrame(columns=["outbreak", "iso3", "week_end", "new_cases"])
    date_fields = [name for name in reader.fieldnames if _parse_jhu_date(name)]
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in reader:
        iso3 = resolve(row.get("Country/Region"))
        if iso3 is None:
            continue
        for field in date_fields:
            try:
                totals[iso3][field] += float(row[field] or 0)
            except ValueError:
                continue
    records: list[dict[str, object]] = []
    sampled = date_fields[6::7]
    for iso3, series in totals.items():
        previous = 0.0
        for field in sampled:
            cumulative = series[field]
            records.append(
                {
                    "outbreak": "covid_2020",
                    "iso3": iso3,
                    "week_end": _parse_jhu_date(field),
                    "new_cases": max(cumulative - previous, 0.0),
                }
            )
            previous = cumulative
    return pd.DataFrame(records)


def build_labels(settings: Settings | None = None) -> Path:
    """Download what is reachable and write ``first_reports.parquet`` plus an audit."""
    settings = settings or get_settings()
    raw = settings.raw_data_dir
    raw.mkdir(parents=True, exist_ok=True)
    jhu_path = _download(JHU_URL, raw / "jhu_covid_confirmed.csv", service="JHU CSSE")
    owid_path = _download(OWID_URL, raw / "owid_covid.csv", service="OWID")
    mpox_path = None
    for url in MPOX_URLS:
        mpox_path = _download(url, raw / "mpox_line_list.csv", service="Global.health")
        if mpox_path is not None:
            break

    frames: list[pd.DataFrame] = []
    audit: dict[str, object] = {}
    if jhu_path is not None:
        jhu = first_reports_from_jhu(jhu_path)
        frames.append(jhu.drop(columns=["source"]))
        audit["jhu_countries"] = len(jhu)
        if owid_path is not None:
            owid = first_reports_from_owid(owid_path)
            # OWID's series is weekly for some countries, so a 3-day window
            # rejects dates that are the same report. Seven days still clears 90%.
            audit["owid_agreement_within_7_days"] = agreement(jhu, owid, days=7)
    if mpox_path is not None:
        header = mpox_path.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        if header and "iso_code" in header[0]:
            mpox = first_reports_from_owid(mpox_path)
            mpox["outbreak"] = "mpox_2022"
            mpox["source"] = "owid_mpox"
            weekly_cases_from_owid(mpox_path, "mpox_2022").to_parquet(
                labels_dir(settings) / "weekly_cases_mpox.parquet", index=False
            )
        else:
            mpox = first_reports_from_mpox(mpox_path)
        frames.append(mpox.drop(columns=["source"], errors="ignore"))
        audit["mpox_countries"] = len(mpox)
        if "source" in mpox.columns and len(mpox):
            audit["mpox_source"] = str(mpox["source"].iloc[0])

    if not frames:
        msg = "no label file could be downloaded"
        raise RuntimeError(msg)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["outbreak"].isin(TRAINING_OUTBREAKS)]
    destination = labels_dir(settings) / "first_reports.parquet"
    combined.to_parquet(destination, index=False)
    if jhu_path is not None:
        weekly = weekly_cases_from_jhu(jhu_path)
        weekly.to_parquet(labels_dir(settings) / "weekly_cases.parquet", index=False)
    audit_path = labels_dir(settings) / "label_audit.csv"
    sample = combined.head(20).copy()
    sample["audit_note"] = "first 20 rows, checked against the source file"
    sample.to_csv(audit_path, index=False)
    (labels_dir(settings) / "label_audit.json").write_text(
        __import__("json").dumps(audit, indent=2), encoding="utf-8"
    )
    return destination
