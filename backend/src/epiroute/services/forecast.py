"""Which countries that have not reported yet are most likely to report next."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import numpy as np
from sqlalchemy.orm import Session

from epiroute.calibration.hazard import HazardCoefficients, probability
from epiroute.calibration.train import calibration_status, load_card
from epiroute.core.clock import utc_now
from epiroute.epidemiology import prevalence as prev
from epiroute.repositories import outbreaks as outbreak_repo
from epiroute.repositories import reference as reference_repo
from epiroute.schemas.risk import RiskQuery
from epiroute.services.risk import (
    PRESENCE_LOOKBACK_DAYS,
    _origin_prevalence,
    _profile_for,
    _resolve_focus,
)


def rank_next_countries(
    session: Session,
    query: RiskQuery,
    *,
    limit: int = 20,
) -> dict[str, object]:
    """Rank destinations by the chance of a first report within the horizon.

    Origins are computed once. Each destination then receives the flows that
    leave those origins. Countries that already have a report are left off the list.
    """
    moment = query.as_of or utc_now()
    anchor = reference_repo.list_countries(session)
    anchor_iso3 = anchor[0].iso3 if anchor else "USA"
    focus, _warnings = _resolve_focus(session, anchor_iso3, query)
    profile, _key, _profile_warnings = _profile_for(focus)
    window = moment - timedelta(days=PRESENCE_LOOKBACK_DAYS)
    reported = outbreak_repo.countries_with_active_outbreaks(
        session,
        pathogen_key=None if focus.disease_key else profile.key,
        disease_label=focus.disease_label,
        disease_key=focus.disease_key,
        since=window,
        until=moment,
    )
    origin_prevalence: dict[str, float] = {}
    for origin in reported:
        country = reference_repo.get_country(session, origin)
        if country is None or not country.population:
            continue
        outcome = _origin_prevalence(
            session, origin, profile, query, country.population, focus, as_of=moment
        )
        if isinstance(outcome, prev.PrevalenceEstimate):
            origin_prevalence[origin] = outcome.central
    origin_alpha = query.alpha if query.alpha is not None else profile.alpha.central
    sigma = query.sigma

    rates: dict[str, float] = defaultdict(float)
    for flow in reference_repo.all_flows(session):
        prevalence = origin_prevalence.get(flow.origin_iso3)
        if prevalence is None or flow.dest_iso3 in origin_prevalence:
            continue
        rates[flow.dest_iso3] += prevalence * flow.passengers_per_day * origin_alpha * (1.0 - sigma)

    status = calibration_status()
    card = load_card()
    ranked: list[dict[str, object]] = []
    for iso3, rate in rates.items():
        country = reference_repo.get_country(session, iso3)
        population = country.population if country and country.population else 10_000_000
        outbreak = {"covid_19": "covid_2020", "mpox": "mpox_2022"}.get(profile.key or "")
        if outbreak is None:
            status = "not_validated"
        chance = _chance(
            rate, population, query.horizon_days, status, card, outbreak=outbreak
        )
        ranked.append(
            {
                "iso3": iso3,
                "name": country.name if country else iso3,
                "probability": chance,
                "arrival_rate_per_day": rate,
            }
        )
    ranked.sort(key=lambda row: float(row["probability"]), reverse=True)
    return {
        "calibration_status": status,
        "horizon_days": query.horizon_days,
        "countries": ranked[:limit],
    }


def _chance(
    rate: float,
    population: int,
    horizon: float,
    status: str,
    card: dict[str, object] | None,
    *,
    outbreak: str | None,
) -> float:
    """Use the fold that held this outbreak out. Anything else stays uncalibrated.

    The fit is for a 28-day horizon. A different horizon is not that model.
    """
    uncalibrated = float(1.0 - np.exp(-rate * horizon))
    if status != "calibrated" or card is None or horizon != 28.0 or outbreak is None:
        return uncalibrated
    folds = card.get("folds")
    if not isinstance(folds, list):
        return uncalibrated
    match = next(
        (
            fold
            for fold in folds
            if isinstance(fold, dict)
            and fold.get("held_out") == outbreak
            and not fold.get("skipped")
        ),
        None,
    )
    if not isinstance(match, dict) or "serve_b0" not in match:
        return uncalibrated
    b1 = match.get("serve_b1")
    g = match.get("serve_g")
    if not isinstance(b1, (int, float)) or not isinstance(g, (int, float)) or b1 < 0:
        return uncalibrated
    log_lambda = np.array([np.log(max(rate, 1e-12))])
    log_population = np.array([np.log10(population)])
    coefficients = HazardCoefficients(float(match["serve_b0"]), float(b1), float(g))
    return float(probability(coefficients, log_lambda, log_population, horizon)[0])
