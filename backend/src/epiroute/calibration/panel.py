"""One row per destination per forecast week, using only data available that week."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from epiroute.calibration.labels import labels_dir
from epiroute.core.config import Settings, get_settings

OUTBREAK_YEAR = {"covid_2020": 2019, "mpox_2022": 2022}
HORIZON_DAYS = 28
WEEKS = 16
ALPHA = 0.5
INFECTIOUS_DAYS = 7.0
UNDERREPORTING = 4.0


def _flows(settings: Settings, year: int) -> pd.DataFrame:
    path = settings.processed_data_dir / f"flows_{year}.parquet"
    if not path.exists():
        msg = f"missing {path.name}; run data-fetch and data-build for Eurostat {year}"
        raise FileNotFoundError(msg)
    frame = pd.read_parquet(path)
    return frame[frame["value_type"] == "observed"] if "value_type" in frame.columns else frame


def build_panel(settings: Settings | None = None) -> Path:
    """Forecast rows for countries that had not yet reported.

    Lambda uses the previous week's new cases, so the label week is not an input.
    Population is a column on the flow file's countries when present; otherwise
    the destination's total inbound passengers stand in only as a size feature
    stored separately, and population defaults to 1e7 with ``population_imputed``.
    """
    settings = settings or get_settings()
    reports = pd.read_parquet(labels_dir(settings) / "first_reports.parquet")
    reports["first_report"] = pd.to_datetime(reports["first_report"])
    populations = _populations(settings)
    rows: list[dict[str, object]] = []

    for outbreak, year in OUTBREAK_YEAR.items():
        subset = reports[reports["outbreak"] == outbreak]
        if subset.empty:
            continue
        flows = _flows(settings, year)
        by_origin = {
            origin: group.set_index("dest_iso3")["passengers_per_day"].to_dict()
            for origin, group in flows.groupby("origin_iso3")
        }
        weekly = _weekly(settings, outbreak)
        start = subset["first_report"].min()
        first = dict(zip(subset["iso3"], subset["first_report"], strict=False))
        countries = sorted(set(populations) | set(first))
        for week in range(1, WEEKS + 1):
            forecast_at = start + timedelta(days=7 * week)
            affected = [iso3 for iso3, when in first.items() if when <= forecast_at]
            if len(affected) < 1:
                continue
            for destination in countries:
                if destination in affected:
                    continue
                inbound = 0.0
                arrival_rate = 0.0
                for origin in affected:
                    passengers = float(by_origin.get(origin, {}).get(destination, 0.0))
                    inbound += passengers
                    origin_population = populations.get(origin, 1.0e7)
                    incidence = _recent_incidence(weekly, origin, forecast_at)
                    prevalence = incidence * INFECTIOUS_DAYS * UNDERREPORTING / origin_population
                    arrival_rate += prevalence * passengers * ALPHA
                reported_by = first.get(destination)
                if reported_by is None:
                    within = False
                    arrival_day = float("nan")
                else:
                    gap = (reported_by - forecast_at).days
                    within = 0 < gap <= HORIZON_DAYS
                    arrival_day = gap
                rows.append(
                    {
                        "outbreak": outbreak,
                        "destination": destination,
                        "forecast_at": forecast_at,
                        "latest_input_at": forecast_at,
                        "lambda": arrival_rate,
                        "inbound_passengers": inbound,
                        "log_population": float(np.log10(populations.get(destination, 1.0e7))),
                        "label": int(within),
                        "arrival_day": arrival_day,
                        "population_imputed": destination not in populations,
                    }
                )

    if not rows:
        msg = "the training panel is empty"
        raise RuntimeError(msg)
    frame = pd.DataFrame(rows)
    target = labels_dir(settings) / "panel.parquet"
    frame.to_parquet(target, index=False)
    return target


def _weekly(settings: Settings, outbreak: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for name in ("weekly_cases.parquet", "weekly_cases_mpox.parquet"):
        path = labels_dir(settings) / name
        if path.exists():
            frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame(columns=["iso3", "week_end", "new_cases"])
    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame["outbreak"] == outbreak]
    frame["week_end"] = pd.to_datetime(frame["week_end"])
    return frame


def _recent_incidence(weekly: pd.DataFrame, iso3: str, forecast_at: pd.Timestamp) -> float:
    """New cases per day in the latest week that had already been published."""
    if weekly.empty:
        return 1.0 / 7.0
    country = weekly[(weekly["iso3"] == iso3) & (weekly["week_end"] <= forecast_at)]
    if country.empty:
        return 1.0 / 7.0
    latest = country.sort_values("week_end").iloc[-1]
    return float(latest["new_cases"]) / 7.0


def _populations(settings: Settings) -> dict[str, float]:
    path = settings.processed_data_dir / "countries.parquet"
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    if "population" not in frame.columns:
        return {}
    return {
        str(row.iso3): float(row.population)
        for row in frame.itertuples(index=False)
        if row.population and row.population > 0
    }
