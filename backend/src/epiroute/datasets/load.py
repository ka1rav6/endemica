from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from epiroute.core.clock import utc_now
from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import DataUnavailableError
from epiroute.datasets.build import (
    COUNTRIES_TABLE,
    FLOWS_TABLE,
    GRAVITY_FILE,
    TOPOLOGY_TABLE,
)
from epiroute.datasets.fetch import file_sha256
from epiroute.datasets.registry import DATASETS
from epiroute.db.models import Country, CountryFlow, DatasetVersion, GravityModelFit

logger = logging.getLogger(__name__)

_CHUNK = 2000


@dataclass(frozen=True, slots=True)
class LoadResult:
    countries: int
    flows: int
    dataset_versions: int
    gravity_fits: int


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    subset = frame[[c for c in columns if c in frame.columns]]
    out: list[dict[str, Any]] = []
    for row in subset.to_dict(orient="records"):
        out.append({str(k): (None if pd.isna(v) else v) for k, v in row.items()})
    return out


def _as_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def load_countries(session: Session, path: Path) -> int:
    frame = pd.read_parquet(path)
    columns = [
        "iso3",
        "iso2",
        "name",
        "official_name",
        "region",
        "subregion",
        "population",
        "population_year",
        "population_source",
        "centroid_lat",
        "centroid_lon",
    ]
    rows = _records(frame, columns)
    for row in rows:
        for key in ("population", "population_year"):
            row[key] = _as_int(row.get(key))
        for key in ("centroid_lat", "centroid_lon"):
            row[key] = _as_float(row.get(key))

    for start in range(0, len(rows), _CHUNK):
        chunk = rows[start : start + _CHUNK]
        statement = insert(Country).values(chunk)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Country.iso3],
                set_={column: statement.excluded[column] for column in columns if column != "iso3"},
            )
        )
    return len(rows)


def load_flows(session: Session, path: Path) -> int:
    frame = pd.read_parquet(path)
    if frame.empty:
        return 0
    known = set(session.scalars(select(Country.iso3)).all())
    frame = frame[frame["origin_iso3"].isin(known) & frame["dest_iso3"].isin(known)]
    frame = frame[frame["origin_iso3"] != frame["dest_iso3"]]

    columns = [
        column
        for column in (
            "origin_iso3",
            "dest_iso3",
            "passengers_per_day",
            "value_type",
            "source",
            "reference_period",
            "uncertainty_factor",
            "direct_route_count",
            "cross_check_source",
            "cross_check_ratio",
        )
        if column in frame.columns
    ]
    rows = _records(frame, columns)
    for row in rows:
        row["passengers_per_day"] = float(row["passengers_per_day"])
        row["uncertainty_factor"] = _as_float(row.get("uncertainty_factor"))
        row["direct_route_count"] = _as_int(row.get("direct_route_count"))

    session.execute(delete(CountryFlow))
    for start in range(0, len(rows), _CHUNK):
        session.execute(insert(CountryFlow).values(rows[start : start + _CHUNK]))
    return len(rows)


def load_gravity_fit(session: Session, path: Path) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    session.query(GravityModelFit).update({GravityModelFit.is_active: False})
    session.add(
        GravityModelFit(
            fitted_at=utc_now(),
            specification=payload["specification"],
            feature_names=payload["feature_names"],
            coefficients=payload["coefficients"],
            intercept=payload["intercept"],
            training_source=payload["training_source"],
            training_period=payload.get("training_period"),
            n_train=payload["n_train"],
            n_test=payload["n_test"],
            random_seed=payload["random_seed"],
            metrics=payload["test_metrics"],
            residual_sigma_log10=payload["residual_sigma_log10"],
            is_active=True,
            notes=payload.get("notes"),
        )
    )
    return 1


def record_dataset_versions(session: Session, settings: Settings) -> int:
    count = 0
    for key, spec in DATASETS.items():
        path = settings.raw_data_dir / spec.filename
        if not path.exists():
            continue
        session.query(DatasetVersion).filter(
            DatasetVersion.dataset == key, DatasetVersion.is_active.is_(True)
        ).update({DatasetVersion.is_active: False})
        stat = path.stat()
        session.add(
            DatasetVersion(
                dataset=key,
                source_name=spec.name,
                source_url=spec.url,
                retrieved_at=pd.Timestamp(stat.st_mtime, unit="s", tz="UTC").to_pydatetime(),
                reference_period=None,
                record_count=None,
                content_sha256=file_sha256(path),
                license_note=spec.licence,
                notes={
                    "filename": spec.filename,
                    "bytes": stat.st_size,
                    "coverage": spec.coverage,
                    "limitations": list(spec.limitations),
                    "fields_used": list(spec.fields_used),
                },
                is_active=True,
            )
        )
        count += 1
    return count


def load_reference_data(session: Session, *, settings: Settings | None = None) -> LoadResult:
    settings = settings or get_settings()
    processed = settings.processed_data_dir
    countries_path = processed / COUNTRIES_TABLE
    if not countries_path.exists():
        msg = "processed tables are missing; run `just data-build`"
        raise DataUnavailableError("processed_tables", msg)

    countries = load_countries(session, countries_path)
    session.flush()
    flows_path = processed / FLOWS_TABLE
    flows = load_flows(session, flows_path) if flows_path.exists() else 0
    gravity = load_gravity_fit(session, processed / GRAVITY_FILE)
    versions = record_dataset_versions(session, settings)

    topology_path = processed / TOPOLOGY_TABLE
    if topology_path.exists():
        logger.info(
            "topology table left in parquet",
            extra={"path": str(topology_path), "reason": "read-only, build-step only"},
        )

    logger.info(
        "reference data loaded",
        extra={"countries": countries, "flows": flows, "dataset_versions": versions},
    )
    return LoadResult(
        countries=countries, flows=flows, dataset_versions=versions, gravity_fits=gravity
    )
