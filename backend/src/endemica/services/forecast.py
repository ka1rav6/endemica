"""Which countries that have not reported yet are most likely to report next.

The fitted model used to be unreachable from here. Serving looked up the
leave-one-out fold whose held-out outbreak matched the live one, which exists
only for COVID-19 and mpox, and the card itself was never written on a fresh
checkout because building the panel needed Eurostat downloads that
``data-fetch`` does not perform. Every disease in the app therefore got
``1 - exp(-lambda * 28)``, which scores AUC 0.54 and 0.62 on the two held-out
outbreaks against the model's 0.78 and 0.77.

Now the card carries one coefficient vector fitted on the whole panel and this
module serves it to every disease, with three things kept honest about it:

* the status says what the evidence supports - a calibrated probability, an
  ordering with an indicative level, or nothing;
* the band comes from refitting without each outbreak, so it is the spread
  between a model that never saw COVID-19 and one that never saw mpox;
* a destination with no arriving passengers from any affected country gets no
  number at all, because the curve would return its intercept there and an
  intercept is not a finding about that country.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import timedelta

import numpy as np
from sqlalchemy.orm import Session

from endemica.calibration.features import HORIZON_DAYS, FeatureRow, design_matrix
from endemica.calibration.hazard import cloglog_probability
from endemica.calibration.train import (
    band_coefficients,
    calibration_status,
    load_card,
    served_coefficients,
)
from endemica.core.clock import utc_now
from endemica.epidemiology import prevalence as prev
from endemica.repositories import outbreaks as outbreak_repo
from endemica.repositories import reference as reference_repo
from endemica.schemas.risk import RiskQuery
from endemica.services.risk import (
    PRESENCE_LOOKBACK_DAYS,
    _profile_for,
    _resolve_focus,
    prevalence_from_cumulative,
)

# The outbreaks the panel was built from. A live outbreak of one of these is
# the only case where the model is scoring a pathogen it has actually seen, and
# the card's status is reported as-is. Anything else is a transfer, which the
# response says so that the reader is not told a held-out number is a fitted
# one.
PANEL_OUTBREAKS = {"covid_19": "covid_2020", "mpox": "mpox_2022"}


def rank_next_countries(
    session: Session,
    query: RiskQuery,
    *,
    limit: int = 20,
) -> dict[str, object]:
    """Rank destinations by the chance of a first report within the horizon.

    Origins are computed once. Each destination then receives the flows that
    leave those origins. Countries that already have a report are left off.
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
    # One lookup for every country, and one query for every origin's series.
    # Both used to run once per country, which COVID-19's 227 reporting
    # countries turned into several hundred round trips for one request.
    by_iso3 = {country.iso3: country for country in anchor}
    series_by_origin = outbreak_repo.cumulative_series_by_country(
        session,
        reported,
        profile.key or "",
        disease_label=focus.disease_label,
        disease_key=focus.disease_key,
        as_of=moment,
    )
    origin_prevalence: dict[str, float] = {}
    fatality_ratio = outbreak_repo.disease_fatality_ratio(
        session,
        disease_key=focus.disease_key,
        pathogen_key=None if focus.disease_key else profile.key,
    )
    for origin in reported:
        country = by_iso3.get(origin)
        if country is None or not country.population:
            continue
        outcome = prevalence_from_cumulative(
            series_by_origin.get(origin, []),
            profile=profile,
            query=query,
            population=country.population,
            focus=focus,
            as_of=moment,
            fatality_ratio=fatality_ratio,
        )
        if isinstance(outcome, prev.PrevalenceEstimate):
            origin_prevalence[origin] = outcome.central
    origin_alpha = query.alpha if query.alpha is not None else profile.alpha.central
    sigma = query.sigma

    rates: dict[str, float] = defaultdict(float)
    inbound: dict[str, float] = defaultdict(float)
    for flow in reference_repo.all_flows(session):
        prevalence = origin_prevalence.get(flow.origin_iso3)
        if prevalence is None or flow.dest_iso3 in origin_prevalence:
            continue
        rates[flow.dest_iso3] += prevalence * flow.passengers_per_day * origin_alpha * (1.0 - sigma)
        inbound[flow.dest_iso3] += flow.passengers_per_day

    # The affected count is a feature of the whole outbreak, not of a
    # destination, and is the observable that replaced the per-outbreak
    # intercept the model used to need.
    affected_count = len(origin_prevalence)
    model = _Model.load(query.horizon_days, focus_key=profile.key)

    scored: list[_Ranked] = []
    for iso3, rate in rates.items():
        country = by_iso3.get(iso3)
        row = FeatureRow(
            arrival_rate_per_day=rate,
            inbound_passengers_per_day=inbound[iso3],
            affected_country_count=affected_count,
        )
        central, low, high, basis = model.predict(row, query.horizon_days)
        scored.append(
            _Ranked(
                iso3=iso3,
                name=country.name if country else iso3,
                probability=central,
                probability_low=low,
                probability_high=high,
                basis=basis,
                arrival_rate_per_day=rate,
                inbound_passengers_per_day=inbound[iso3],
            )
        )
    # A country with no answer sorts last rather than as a zero, so "we cannot
    # say" never reads as "almost certainly not".
    scored.sort(key=lambda entry: (entry.probability is None, -(entry.probability or 0.0)))
    ranked = [entry.as_dict() for entry in scored]
    return {
        "calibration_status": model.status,
        "model_version": model.version,
        "horizon_days": query.horizon_days,
        "affected_origin_count": affected_count,
        "note": model.note,
        "countries": ranked[:limit],
    }


@dataclass(frozen=True, slots=True)
class _Ranked:
    iso3: str
    name: str
    probability: float | None
    probability_low: float | None
    probability_high: float | None
    basis: str
    arrival_rate_per_day: float
    inbound_passengers_per_day: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class _Model:
    """The served coefficients, or the fallback arithmetic, with a note saying which."""

    def __init__(
        self,
        beta: np.ndarray | None,
        band: list[np.ndarray],
        status: str,
        version: str,
        note: str,
    ) -> None:
        self._beta = beta
        self._band = band
        self.status = status
        self.version = version
        self.note = note

    @classmethod
    def load(cls, horizon_days: float, *, focus_key: str | None) -> _Model:
        card = load_card()
        status = calibration_status()
        if card is None or status == "not_validated":
            return cls(
                None,
                [],
                "not_validated",
                "uncalibrated-poisson",
                "No validated model card on this checkout. Showing 1 - exp(-rate * "
                "horizon), which is the arrival-rate arithmetic with nothing fitted. "
                "Run just train-model.",
            )
        if horizon_days != HORIZON_DAYS:
            return cls(
                None,
                [],
                "not_validated",
                "uncalibrated-poisson",
                f"The model is fitted for a {int(HORIZON_DAYS)}-day horizon and this "
                f"request asked for {horizon_days:g} days. A different horizon is a "
                "different model, so the arrival-rate arithmetic is shown instead.",
            )
        beta = served_coefficients(card)
        if beta is None:
            return cls(
                None,
                [],
                "not_validated",
                "uncalibrated-poisson",
                "The model card does not carry usable coefficients. Showing the "
                "arrival-rate arithmetic instead.",
            )
        version = str(card.get("model_version") or "hazard")
        in_panel = focus_key in PANEL_OUTBREAKS
        if status == "calibrated" and in_panel:
            note = (
                "Fitted probability for a pathogen in the training panel, with both "
                "the ordering and the level validated on a held-out outbreak."
            )
        elif status == "calibrated":
            note = (
                "Fitted probability, transferred to a pathogen outside the training "
                "panel. The ordering and the level were validated on held-out "
                "outbreaks, but not on this one."
            )
        else:
            note = (
                "The ordering is validated on both held-out outbreaks; the absolute "
                "level is not, because the two differ threefold in base rate. Read "
                "the order, treat the percentage as indicative, and see the band."
            )
            if not in_panel:
                note += " This pathogen is not in the training panel."
        return cls(beta, band_coefficients(card), status, version, note)

    def predict(
        self, row: FeatureRow, horizon_days: float
    ) -> tuple[float | None, float | None, float | None, str]:
        if not row.has_evidence:
            # No passengers arrive here from anywhere that has reported. The
            # fitted curve would return its intercept, which says nothing about
            # this country, so the answer is that there is no answer.
            return None, None, None, "no_inbound_travel_from_affected_countries"
        if self._beta is None:
            rate = max(row.arrival_rate_per_day, 0.0)
            return float(1.0 - np.exp(-rate * horizon_days)), None, None, "uncalibrated_rate"
        design = design_matrix([row])
        central = float(cloglog_probability(design, self._beta, horizon_days)[0])
        bounds = [
            float(cloglog_probability(design, vector, horizon_days)[0]) for vector in self._band
        ]
        low = min(bounds) if bounds else None
        high = max(bounds) if bounds else None
        return central, low, high, "fitted_hazard"
