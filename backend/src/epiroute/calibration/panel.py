"""One row per destination per forecast week, using only data available that week.

Each row answers: given what was known on this date, did this country report
its first case in the next 28 days? The features are built by
:mod:`epiroute.calibration.features`, the same function the live ranking uses,
so a coefficient means the same thing in both places.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from epiroute.calibration.labels import labels_dir
from epiroute.core.config import Settings, get_settings

OUTBREAK_YEAR = {"covid_2020": 2019, "mpox_2022": 2022}
HORIZON_DAYS = 28
WEEKS = 16

# The share of travellers from an infected country who are infectious enough to
# seed a chain elsewhere. One value for every outbreak in the panel, because
# fitting it per outbreak would let the panel encode which outbreak a row came
# from, which is exactly what the model is not allowed to know.
ALPHA = 0.5
INFECTIOUS_DAYS = 7.0

# Reported cases undercount infections. Four is the low end of the published
# serological multipliers for early COVID-19 and is applied to both outbreaks
# rather than tuned, so it shifts every row's arrival rate by the same factor
# and cannot change the ranking it is fitted on.
UNDERREPORTING = 4.0

CURRENT_FLOWS = "country_flows.parquet"


def _era_flows(settings: Settings, year: int) -> tuple[pd.DataFrame, str]:
    """Passenger flows for a backtest week, and a note on which table they came from.

    The era tables hold Eurostat's observed counts for the outbreak's own year
    and are the right answer when they are there. They need 34 reporting
    countries fetched twice each from the Eurostat API for every year, so most
    checkouts do not have them, and this used to raise and leave `train-model`
    permanently broken - the model had never been fitted on this machine at
    all. Falling back to the current table is a real loss of fidelity, named in
    the panel and in the evaluation report rather than hidden: the flows are
    from a later year, and most of them are gravity estimates rather than
    counts.
    """
    era = settings.processed_data_dir / f"flows_{year}.parquet"
    if era.exists():
        frame = pd.read_parquet(era)
        if "value_type" in frame.columns:
            frame = frame[frame["value_type"] == "observed"]
        return frame, f"eurostat_observed_{year}"

    current = settings.processed_data_dir / CURRENT_FLOWS
    if not current.exists():
        msg = f"missing {CURRENT_FLOWS}; run just data-fetch && just data-build"
        raise FileNotFoundError(msg)
    return pd.read_parquet(current), "current_table_observed_and_estimated"


def _flow_lookup(frame: pd.DataFrame) -> dict[str, dict[str, tuple[float, float]]]:
    """``origin -> destination -> (passengers per day, observed passengers per day)``."""
    observed = (
        frame["value_type"].eq("observed")
        if "value_type" in frame.columns
        else pd.Series(True, index=frame.index)
    )
    lookup: dict[str, dict[str, tuple[float, float]]] = {}
    for origin, destination, passengers, is_observed in zip(
        frame["origin_iso3"],
        frame["dest_iso3"],
        frame["passengers_per_day"],
        observed,
        strict=False,
    ):
        value = float(passengers)
        lookup.setdefault(str(origin), {})[str(destination)] = (
            value,
            value if bool(is_observed) else 0.0,
        )
    return lookup


def build_panel(settings: Settings | None = None) -> Path:
    """Write ``panel.parquet`` and a provenance file beside it."""
    settings = settings or get_settings()
    reports = pd.read_parquet(labels_dir(settings) / "first_reports.parquet")
    reports["first_report"] = pd.to_datetime(reports["first_report"])
    populations = _populations(settings)
    rows: list[dict[str, object]] = []
    eras: dict[str, str] = {}

    for outbreak, year in OUTBREAK_YEAR.items():
        subset = reports[reports["outbreak"] == outbreak]
        if subset.empty:
            continue
        flows, era = _era_flows(settings, year)
        eras[outbreak] = era
        by_origin = _flow_lookup(flows)
        weekly = _weekly(settings, outbreak)
        start = subset["first_report"].min()
        first = dict(zip(subset["iso3"], subset["first_report"], strict=False))
        countries = sorted(set(populations) | set(first))
        weeks = [(week, start + timedelta(days=7 * week)) for week in range(1, WEEKS + 1)]
        # Prevalence is a property of the origin and the week, so it is worked
        # out once per pair. Inside the destination loop it was one lookup per
        # origin per destination per week, a quarter of a million of them for
        # COVID-19 alone, which is why building the panel took minutes.
        incidence = _incidence_lookup(weekly)
        prevalence_at = {
            (origin, week): (
                incidence(origin, forecast_at)
                * INFECTIOUS_DAYS
                * UNDERREPORTING
                / populations.get(origin, 1.0e7)
            )
            for week, forecast_at in weeks
            for origin in first
        }
        for week, forecast_at in weeks:
            affected = [iso3 for iso3, when in first.items() if when <= forecast_at]
            if not affected:
                continue
            for destination in countries:
                if destination in affected:
                    continue
                inbound = 0.0
                observed_inbound = 0.0
                arrival_rate = 0.0
                for origin in affected:
                    passengers, observed_passengers = by_origin.get(origin, {}).get(
                        destination, (0.0, 0.0)
                    )
                    if passengers <= 0.0:
                        continue
                    inbound += passengers
                    observed_inbound += observed_passengers
                    arrival_rate += prevalence_at[(origin, week)] * passengers * ALPHA
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
                        "week_index": week,
                        "lambda": arrival_rate,
                        "inbound_passengers": inbound,
                        "observed_passenger_share": (
                            observed_inbound / inbound if inbound > 0 else 0.0
                        ),
                        "affected_count": len(affected),
                        "log_population": float(np.log10(populations.get(destination, 1.0e7))),
                        "label": int(within),
                        "arrival_day": arrival_day,
                        "population_imputed": destination not in populations,
                        "flow_era": era,
                    }
                )

    if not rows:
        msg = "the training panel is empty"
        raise RuntimeError(msg)
    frame = pd.DataFrame(rows)
    # Sorted so the file's bytes depend on its contents and not on dict order,
    # which is what lets two checkouts compare panel hashes and mean it.
    frame = frame.sort_values(["outbreak", "forecast_at", "destination"]).reset_index(drop=True)
    target = labels_dir(settings) / "panel.parquet"
    frame.to_parquet(target, index=False)
    (labels_dir(settings) / "panel_provenance.json").write_text(
        json.dumps(
            {
                "rows": len(frame),
                "positives": int(frame["label"].sum()),
                "weeks_per_outbreak": WEEKS,
                "horizon_days": HORIZON_DAYS,
                "alpha": ALPHA,
                "underreporting": UNDERREPORTING,
                "flow_era": eras,
                "zero_rate_share": float((frame["lambda"] <= 0).mean()),
                "observed_passenger_share_mean": float(frame["observed_passenger_share"].mean()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
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


def _incidence_lookup(weekly: pd.DataFrame) -> Callable[[str, pd.Timestamp], float]:
    """A function giving new cases per day in the latest week published by a date.

    The table is split by country once and searched by bisection, so a lookup
    does not get slower as the case history gets longer. A country with nothing
    published by that date falls back to one case a week, which keeps an origin
    that is known to be infected from contributing an arrival rate of zero.
    """
    if weekly.empty:
        return lambda _iso3, _forecast_at: 1.0 / 7.0
    ordered = weekly.sort_values("week_end")
    series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for iso3, group in ordered.groupby("iso3"):
        series[str(iso3)] = (
            group["week_end"].to_numpy(dtype="datetime64[ns]"),
            group["new_cases"].to_numpy(dtype=float),
        )

    def incidence(iso3: str, forecast_at: pd.Timestamp) -> float:
        found = series.get(iso3)
        if found is None:
            return 1.0 / 7.0
        week_ends, cases = found
        index = int(np.searchsorted(week_ends, np.datetime64(forecast_at), side="right")) - 1
        if index < 0:
            return 1.0 / 7.0
        return float(cases[index]) / 7.0

    return incidence


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
