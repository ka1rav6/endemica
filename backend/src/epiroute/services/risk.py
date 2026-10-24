from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import timedelta

from sqlalchemy.orm import Session

from epiroute import __version__
from epiroute.core.clock import utc_now
from epiroute.core.errors import NotFoundError
from epiroute.datasets.iso import country_name
from epiroute.epidemiology import establishment as est
from epiroute.epidemiology import importation as imp
from epiroute.epidemiology import prevalence as prev
from epiroute.epidemiology.effective_distance import (
    build_effective_distance_graph,
    rank_origins_by_effective_distance,
)
from epiroute.epidemiology.profiles import (
    DEFAULT_PROFILE_KEY,
    PathogenProfile,
    get_profile,
)
from epiroute.repositories import outbreaks as outbreak_repo
from epiroute.repositories import reference as reference_repo
from epiroute.schemas.common import (
    Assumption,
    BandedQuantity,
    DataFreshness,
    Quantity,
    ResponseWarning,
    UnavailableReason,
    ValueType,
)
from epiroute.schemas.risk import (
    EstablishmentRisk,
    ImportationRisk,
    LocalPresence,
    OriginContributionOut,
    PathogenSummary,
    PresenceStatus,
    RiskQuery,
    RiskResponse,
    ScenarioMarker,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = f"epiroute-{__version__}"

DISCLAIMER = (
    "Situational awareness and education only. Not a diagnostic tool, not an official "
    "forecast, and not a substitute for WHO or national travel guidance."
)

PRESENCE_LOOKBACK_DAYS = 90
SCENARIO_UNDERREPORTING_HIGH = 10.0


@dataclass(frozen=True, slots=True)
class _OriginInput:
    iso3: str
    prevalence: prev.PrevalenceEstimate
    passengers_per_day: float
    passengers_value_type: ValueType
    passengers_source: str
    uncertainty_factor: float | None
    reported_cases: int | None
    report_url: str | None
    report_published_at: object


def _resolve_profile(
    session: Session, requested_key: str | None
) -> tuple[PathogenProfile | None, str | None, list[ResponseWarning]]:
    warnings: list[ResponseWarning] = []
    if requested_key:
        return get_profile(requested_key), requested_key, warnings

    recent = outbreak_repo.list_reports(session, limit=1)
    if recent and recent[0].pathogen_key:
        key = recent[0].pathogen_key
        warnings.append(
            ResponseWarning(
                code="pathogen_inferred",
                message=(
                    f"No pathogen was requested, so parameters were taken from the most "
                    f"recent report's profile ({key})."
                ),
                severity="info",
            )
        )
        return get_profile(key), key, warnings

    warnings.append(
        ResponseWarning(
            code="pathogen_defaulted",
            message=(
                f"No pathogen was requested and none could be inferred, so the "
                f"'{DEFAULT_PROFILE_KEY}' profile was used. Its parameters are "
                f"assumptions, not measurements for any specific outbreak."
            ),
            severity="important",
        )
    )
    return get_profile(DEFAULT_PROFILE_KEY), None, warnings


def _build_presence(
    session: Session,
    destination_iso3: str,
    pathogen_key: str | None,
    *,
    disease_label: str | None = None,
) -> LocalPresence:
    rows = outbreak_repo.verified_observations_for_country(
        session, destination_iso3, pathogen_key=pathogen_key, disease_label=disease_label
    )
    if not rows:
        return LocalPresence(
            status=PresenceStatus.NOT_REPORTED,
            value_type=ValueType.OBSERVED,
            detail=(
                "No source report in EpiRoute attributes a grounded case count for this "
                "pathogen to this country. Absence of a report is not evidence of absence "
                "of disease, and flight connectivity is never used as evidence of presence."
            ),
            report_count=0,
        )

    cutoff = utc_now() - timedelta(days=PRESENCE_LOOKBACK_DAYS)
    recent = [
        (obs, rep)
        for obs, rep in rows
        if rep.published_at is not None and rep.published_at >= cutoff
    ]
    considered = recent or rows
    latest = considered[0][1]
    best_cases = max(
        (obs.cases_confirmed for obs, _ in considered if obs.cases_confirmed is not None),
        default=None,
    )
    best_deaths = max((obs.deaths for obs, _ in considered if obs.deaths is not None), default=None)
    urls: list[str] = []
    for _, report in considered[:5]:
        if report.source_url not in urls:
            urls.append(report.source_url)

    detail = (
        f"{len(considered)} grounded report(s) attribute cases to this country; the most "
        f"recent was published on "
        f"{latest.published_at.date() if latest.published_at else 'an unknown date'}."
    )
    if not recent:
        detail += (
            f" All reports are older than {PRESENCE_LOOKBACK_DAYS} days, so the outbreak "
            f"may have ended."
        )

    return LocalPresence(
        status=PresenceStatus.REPORTED,
        value_type=ValueType.OBSERVED,
        last_reported_at=latest.published_at,
        cases_confirmed=(
            Quantity.of(float(best_cases), ValueType.OBSERVED, unit="cases")
            if best_cases is not None
            else Quantity.unavailable(UnavailableReason.NO_LOCAL_CASE_DATA)
        ),
        deaths=(
            Quantity.of(float(best_deaths), ValueType.OBSERVED, unit="deaths")
            if best_deaths is not None
            else Quantity.unavailable(UnavailableReason.NO_LOCAL_CASE_DATA)
        ),
        report_count=len(considered),
        source_urls=urls,  # type: ignore[arg-type]
        detail=detail,
    )


def _origin_prevalence(
    session: Session,
    origin_iso3: str,
    profile: PathogenProfile,
    query: RiskQuery,
    population: int,
) -> prev.PrevalenceOutcome:
    if not profile.key:
        return prev.PrevalenceUnavailable("no_pathogen", "no pathogen profile selected")

    series = outbreak_repo.cumulative_series(
        session, origin_iso3, profile.key, disease_label=query.disease_label
    )
    points = [
        prev.ReportedCount(
            published_at=point.published_at,
            cases_confirmed=point.cases_confirmed,
            outbreak_started_on=point.outbreak_started_on,
        )
        for point in series
        if point.cases_confirmed is not None
    ]
    band = (
        query.underreporting_low,
        query.underreporting_central,
        query.underreporting_high,
    )
    outcome = prev.prevalence_from_series(
        points,
        population=population,
        infectious_period_days=profile.infectious_period_days,
        underreporting=band,
        as_of=utc_now(),
    )
    if (
        isinstance(outcome, prev.PrevalenceUnavailable)
        and outcome.reason == "report_too_old"
    ):
        relaxed = prev.prevalence_from_series(
            points,
            population=population,
            infectious_period_days=profile.infectious_period_days,
            underreporting=band,
            as_of=utc_now(),
            max_report_age_days=prev.STALE_REPORT_MAX_AGE_DAYS,
        )
        if isinstance(relaxed, prev.PrevalenceEstimate):
            return replace(
                relaxed,
                caveats=(
                    *relaxed.caveats,
                    "The latest report is older than 60 days. It is still used because it "
                    "is the only grounded case series for this origin. The outbreak may "
                    "have ended.",
                ),
            )
        return relaxed
    return outcome


def _collect_origins(
    session: Session,
    destination_iso3: str,
    profile: PathogenProfile,
    query: RiskQuery,
) -> tuple[list[_OriginInput], list[dict[str, str]], int, bool]:
    window = utc_now() - timedelta(days=PRESENCE_LOOKBACK_DAYS)
    candidates = outbreak_repo.countries_with_active_outbreaks(
        session,
        pathogen_key=profile.key,
        disease_label=query.disease_label,
        since=window,
    )
    used_older_reports = False
    if not candidates:
        candidates = outbreak_repo.countries_with_active_outbreaks(
            session, pathogen_key=profile.key, disease_label=query.disease_label
        )
        used_older_reports = bool(candidates)
    candidates = [c for c in candidates if c != destination_iso3.upper()]
    flows = reference_repo.flows_between(session, candidates, destination_iso3)

    usable: list[_OriginInput] = []
    excluded: list[dict[str, str]] = []

    for origin in candidates:
        country = reference_repo.get_country(session, origin)
        if country is None or not country.population:
            excluded.append({"origin_iso3": origin, "reason": "no population data"})
            continue
        flow = flows.get(origin)
        if flow is None or flow.passengers_per_day <= 0:
            excluded.append(
                {"origin_iso3": origin, "reason": "no passenger flow to this destination"}
            )
            continue
        outcome = _origin_prevalence(session, origin, profile, query, country.population)
        if isinstance(outcome, prev.PrevalenceUnavailable):
            excluded.append({"origin_iso3": origin, "reason": outcome.detail})
            continue

        series = outbreak_repo.cumulative_series(session, origin, profile.key or "")
        latest = series[-1] if series else None
        usable.append(
            _OriginInput(
                iso3=origin,
                prevalence=outcome,
                passengers_per_day=flow.passengers_per_day * query.passenger_scale,
                passengers_value_type=flow.value_type,
                passengers_source=flow.source,
                uncertainty_factor=flow.uncertainty_factor,
                reported_cases=latest.cases_confirmed if latest else None,
                report_url=latest.report_url if latest else None,
                report_published_at=latest.published_at if latest else None,
            )
        )

    return usable, excluded, len(candidates), used_older_reports


def _rate_for_scenario(
    origins: list[_OriginInput], alpha: float, sigma: float, which: str
) -> tuple[float, list[imp.OriginContribution]]:
    contributions: list[imp.OriginContribution] = []
    for origin in origins:
        prevalence = {
            "low": origin.prevalence.low,
            "central": origin.prevalence.central,
            "high": origin.prevalence.high,
        }[which]
        passengers = origin.passengers_per_day
        if origin.uncertainty_factor:
            if which == "low":
                passengers /= origin.uncertainty_factor
            elif which == "high":
                passengers *= origin.uncertainty_factor
        rate = imp.arrival_rate_from_origin(prevalence, passengers, alpha, sigma)
        contributions.append(
            imp.OriginContribution(
                origin_iso3=origin.iso3,
                prevalence=prevalence,
                passengers_per_day=passengers,
                alpha=alpha,
                sigma=sigma,
                rate_per_day=rate,
            )
        )
    aggregate = imp.importation_rate(contributions)
    return aggregate.rate_per_day, list(aggregate.contributions)


def _effective_distances(
    session: Session, destination_iso3: str, origins: list[str]
) -> dict[str, tuple[float, tuple[str, ...]]]:
    if not origins:
        return {}
    flows = reference_repo.all_flows(session)
    graph = build_effective_distance_graph(
        {(f.origin_iso3, f.dest_iso3): f.passengers_per_day for f in flows}
    )
    ranked = rank_origins_by_effective_distance(graph, destination_iso3.upper(), origins)
    return {p.origin: (p.distance, p.intermediate_nodes) for p in ranked}


def compute_risk(session: Session, destination_iso3: str, query: RiskQuery) -> RiskResponse:
    destination = reference_repo.get_country(session, destination_iso3)
    if destination is None:
        raise NotFoundError("country", destination_iso3)

    requested_key = query.pathogen_key
    if requested_key is None and query.disease_label:
        requested_key = outbreak_repo.pathogen_key_for_disease(session, query.disease_label)
    profile, matched_key, warnings = _resolve_profile(session, requested_key)
    assert profile is not None

    alpha = query.alpha if query.alpha is not None else profile.alpha.central
    alpha_low = query.alpha if query.alpha is not None else profile.alpha.low
    alpha_high = query.alpha if query.alpha is not None else profile.alpha.high
    r_central = (
        query.reproduction_number
        if query.reproduction_number is not None
        else profile.reproduction_number.central
    )
    r_low = (
        query.reproduction_number
        if query.reproduction_number is not None
        else profile.reproduction_number.low
    )
    r_high = (
        query.reproduction_number
        if query.reproduction_number is not None
        else profile.reproduction_number.high
    )
    k_central = (
        query.dispersion_k if query.dispersion_k is not None else profile.dispersion_k.central
    )
    k_low = query.dispersion_k if query.dispersion_k is not None else profile.dispersion_k.low
    k_high = query.dispersion_k if query.dispersion_k is not None else profile.dispersion_k.high

    presence = _build_presence(
        session, destination.iso3, profile.key, disease_label=query.disease_label
    )
    origins, excluded, considered, used_older_reports = _collect_origins(
        session, destination.iso3, profile, query
    )
    if used_older_reports:
        warnings.append(
            ResponseWarning(
                code="older_outbreak_reports",
                message=(
                    "No grounded report for this disease was published in the last "
                    f"{PRESENCE_LOOKBACK_DAYS} days, so older reports were used. "
                    "The outbreak may have ended."
                ),
                severity="caution",
            )
        )

    horizon = query.horizon_days
    band_basis = (
        f"scenario range: under-reporting {query.underreporting_low:g}x-"
        f"{query.underreporting_high:g}x"
        + (
            ", modelled passenger flows widened by the gravity model's held-out residual spread"
            if any(o.uncertainty_factor for o in origins)
            else ""
        )
        + (f", boarding probability {alpha_low:g}-{alpha_high:g}" if query.alpha is None else "")
        + ". Not a confidence interval."
    )

    if not origins:
        importation = ImportationRisk(
            probability=BandedQuantity.unavailable(
                UnavailableReason.NO_ACTIVE_OUTBREAK
                if considered == 0
                else UnavailableReason.NO_PREVALENCE_DATA,
                note=(
                    "No origin country has both a grounded prevalence estimate and a "
                    "passenger flow to this destination."
                ),
            ),
            arrival_rate_per_day=BandedQuantity.unavailable(UnavailableReason.NO_PREVALENCE_DATA),
            horizon_days=horizon,
            origin_count_considered=considered,
            origin_count_usable=0,
            excluded_origins=excluded,
        )
        establishment = _unavailable_establishment(
            profile, horizon, r_low, r_central, r_high, k_low, k_central, k_high
        )
        warnings.append(
            ResponseWarning(
                code="importation_not_estimable",
                message=(
                    "Importation risk is not estimable: no origin with reported cases also "
                    "has usable passenger-flow data to this destination."
                ),
                severity="important",
            )
        )
        return _assemble(
            destination,
            profile,
            matched_key,
            query,
            presence,
            importation,
            establishment,
            [],
            warnings,
            session,
            alpha,
            r_central,
            k_central,
        )

    rate_low, _ = _rate_for_scenario(origins, alpha_low, query.sigma, "low")
    rate_central, central_contributions = _rate_for_scenario(origins, alpha, query.sigma, "central")
    rate_high, _ = _rate_for_scenario(origins, alpha_high, query.sigma, "high")

    probability = BandedQuantity(
        low=imp.probability_at_least_one_arrival(rate_low, horizon),
        central=imp.probability_at_least_one_arrival(rate_central, horizon),
        high=imp.probability_at_least_one_arrival(rate_high, horizon),
        value_type=ValueType.MODELLED,
        unit="probability",
        band_basis=band_basis,
    )
    rate_band = BandedQuantity(
        low=rate_low,
        central=rate_central,
        high=rate_high,
        value_type=ValueType.MODELLED,
        unit="infected arrivals/day",
        band_basis=band_basis,
    )

    distances = _effective_distances(session, destination.iso3, [o.iso3 for o in origins])
    by_iso3 = {o.iso3: o for o in origins}
    top: list[OriginContributionOut] = []
    for contribution in central_contributions[: query.max_origins]:
        origin = by_iso3[contribution.origin_iso3]
        distance, hubs = distances.get(contribution.origin_iso3, (None, ()))
        top.append(
            OriginContributionOut(
                origin_iso3=origin.iso3,
                origin_name=country_name(origin.iso3),
                arrival_rate_per_day=contribution.rate_per_day,
                share_of_total=(
                    contribution.rate_per_day / rate_central if rate_central > 0 else 0.0
                ),
                passengers_per_day=contribution.passengers_per_day,
                passengers_value_type=origin.passengers_value_type,
                passengers_source=origin.passengers_source,
                prevalence_central=origin.prevalence.central,
                prevalence_per_100k=origin.prevalence.central * 100_000,
                prevalence_value_type=ValueType.ESTIMATED,
                effective_distance=distance,
                via_hubs=list(hubs),
                reported_cases=origin.reported_cases,
                report_url=origin.report_url,  # type: ignore[arg-type]
                report_published_at=origin.report_published_at,  # type: ignore[arg-type]
            )
        )

    importation = ImportationRisk(
        probability=probability,
        arrival_rate_per_day=rate_band,
        horizon_days=horizon,
        is_saturated=imp.is_saturated(rate_central, horizon),
        origin_count_considered=considered,
        origin_count_usable=len(origins),
        top_origins=top,
        excluded_origins=excluded,
    )

    establishment = _build_establishment(
        profile,
        horizon,
        rate_low,
        rate_central,
        rate_high,
        r_low,
        r_central,
        r_high,
        k_low,
        k_central,
        k_high,
        band_basis,
    )

    markers = _scenario_markers(origins, query, profile, alpha_high, r_high, k_high)

    for origin in origins:
        for caveat in origin.prevalence.caveats:
            warning = ResponseWarning(
                code="prevalence_assumption", message=f"{origin.iso3}: {caveat}", severity="caution"
            )
            if warning not in warnings:
                warnings.append(warning)

    if any(o.passengers_value_type is ValueType.ESTIMATED for o in origins):
        warnings.append(
            ResponseWarning(
                code="modelled_passenger_flows",
                message=(
                    "Some passenger volumes are gravity-model estimates, not observed "
                    "counts. Their held-out error is reflected in the band."
                ),
                severity="caution",
            )
        )

    return _assemble(
        destination,
        profile,
        matched_key,
        query,
        presence,
        importation,
        establishment,
        markers,
        warnings,
        session,
        alpha,
        r_central,
        k_central,
    )


def _unavailable_establishment(
    profile: PathogenProfile,
    horizon: float,
    r_low: float,
    r_central: float,
    r_high: float,
    k_low: float,
    k_central: float,
    k_high: float,
) -> EstablishmentRisk:
    reason = (
        UnavailableReason.MODEL_NOT_APPLICABLE
        if not profile.establishment_estimable
        else UnavailableReason.NO_PREVALENCE_DATA
    )
    return EstablishmentRisk(
        probability_per_introduction=BandedQuantity.unavailable(reason),
        probability_within_horizon=BandedQuantity.unavailable(reason),
        horizon_days=horizon,
        reproduction_number_used=BandedQuantity(
            low=r_low,
            central=r_central,
            high=r_high,
            value_type=ValueType.SCENARIO,
            band_basis="pathogen profile range",
        ),
        dispersion_used=BandedQuantity(
            low=k_low,
            central=k_central,
            high=k_high,
            value_type=ValueType.SCENARIO,
            band_basis="pathogen profile range",
        ),
        detail=profile.establishment_note,
    )


def _build_establishment(
    profile: PathogenProfile,
    horizon: float,
    rate_low: float,
    rate_central: float,
    rate_high: float,
    r_low: float,
    r_central: float,
    r_high: float,
    k_low: float,
    k_central: float,
    k_high: float,
    band_basis: str,
) -> EstablishmentRisk:
    r_band = BandedQuantity(
        low=r_low,
        central=r_central,
        high=r_high,
        value_type=ValueType.SCENARIO,
        band_basis="pathogen profile range",
    )
    k_band = BandedQuantity(
        low=k_low,
        central=k_central,
        high=k_high,
        value_type=ValueType.SCENARIO,
        band_basis="pathogen profile range",
    )

    if not profile.establishment_estimable:
        return EstablishmentRisk(
            probability_per_introduction=BandedQuantity.unavailable(
                UnavailableReason.MODEL_NOT_APPLICABLE, note=profile.establishment_note
            ),
            probability_within_horizon=BandedQuantity.unavailable(
                UnavailableReason.MODEL_NOT_APPLICABLE, note=profile.establishment_note
            ),
            horizon_days=horizon,
            reproduction_number_used=r_band,
            dispersion_used=k_band,
            detail=profile.establishment_note,
        )

    per_intro_low = est.solve_establishment(r_low, k_low).establishment_probability
    per_intro_central = est.solve_establishment(r_central, k_central).establishment_probability
    per_intro_high = est.solve_establishment(r_high, k_high).establishment_probability
    subcritical = per_intro_high == 0.0

    if subcritical:
        detail = (
            f"R is at or below 1 across the whole assumed range "
            f"({r_low:g}-{r_high:g}), so sustained community transmission from an "
            f"introduction has probability zero in this model. "
            f"{profile.establishment_note}"
        )
    else:
        detail = (
            f"Each introduction establishes with probability "
            f"{per_intro_central:.1%} at R={r_central:g}, k={k_central:g}. "
            f"{profile.establishment_note}"
        )

    return EstablishmentRisk(
        probability_per_introduction=BandedQuantity(
            low=per_intro_low,
            central=per_intro_central,
            high=per_intro_high,
            value_type=ValueType.MODELLED,
            unit="probability",
            band_basis="scenario range: reproduction number and dispersion from the "
            "pathogen profile. Not a confidence interval.",
        ),
        probability_within_horizon=BandedQuantity(
            low=est.probability_of_establishment_within(rate_low, horizon, r_low, k_low),
            central=est.probability_of_establishment_within(
                rate_central, horizon, r_central, k_central
            ),
            high=est.probability_of_establishment_within(rate_high, horizon, r_high, k_high),
            value_type=ValueType.MODELLED,
            unit="probability",
            band_basis=band_basis,
        ),
        horizon_days=horizon,
        reproduction_number_used=r_band,
        dispersion_used=k_band,
        subcritical=subcritical,
        detail=detail,
    )


def _scenario_markers(
    origins: list[_OriginInput],
    query: RiskQuery,
    profile: PathogenProfile,
    alpha_high: float,
    r_high: float,
    k_high: float,
) -> list[ScenarioMarker]:
    upper_band = [
        _OriginInput(
            iso3=o.iso3,
            prevalence=o.prevalence,
            passengers_per_day=(
                o.passengers_per_day * o.uncertainty_factor
                if o.uncertainty_factor
                else o.passengers_per_day
            ),
            passengers_value_type=o.passengers_value_type,
            passengers_source=o.passengers_source,
            uncertainty_factor=None,
            reported_cases=o.reported_cases,
            report_url=o.report_url,
            report_published_at=o.report_published_at,
        )
        for o in origins
    ]
    rate, _ = _rate_for_scenario(upper_band, alpha_high, 0.0, "high")
    now = utc_now()

    import_day = imp.days_to_probability_threshold(rate, query.threshold)
    markers = [
        ScenarioMarker(
            key="import_threshold",
            label=f"Upper-band import probability reaches {query.threshold:.0%}",
            day_offset=import_day,
            date=now + timedelta(days=import_day) if import_day else None,
            threshold=query.threshold,
            reached=import_day is not None,
            detail=(
                "Scenario marker, not a safety date. Computed with the high under-reporting "
                "multiplier, the high boarding probability, screening set to zero, and "
                "this period's passenger volumes held constant."
            ),
        )
    ]

    if profile.establishment_estimable:
        establish_day = est.days_to_establishment_threshold(rate, query.threshold, r_high, k_high)
        markers.append(
            ScenarioMarker(
                key="establish_threshold",
                label=f"Upper-band establishment probability reaches {query.threshold:.0%}",
                day_offset=establish_day,
                date=now + timedelta(days=establish_day) if establish_day else None,
                threshold=query.threshold,
                reached=establish_day is not None,
                detail=(
                    "Scenario marker using the high end of R and k. Establishment is a "
                    "separate event from arrival and always follows it."
                ),
            )
        )
    return markers


def _disease_name(
    session: Session, query: RiskQuery, pathogen_key: str | None, destination_iso3: str
) -> str | None:
    if query.disease_label:
        return query.disease_label
    return outbreak_repo.latest_disease_label(
        session, pathogen_key, country_iso3=destination_iso3
    ) or outbreak_repo.latest_disease_label(session, pathogen_key)


def _assemble(
    destination: object,
    profile: PathogenProfile,
    matched_key: str | None,
    query: RiskQuery,
    presence: LocalPresence,
    importation: ImportationRisk,
    establishment: EstablishmentRisk,
    markers: list[ScenarioMarker],
    warnings: list[ResponseWarning],
    session: Session,
    alpha: float,
    r_central: float,
    k_central: float,
) -> RiskResponse:
    iso3 = getattr(destination, "iso3", "")
    name = getattr(destination, "name", None) or country_name(iso3)

    assumptions = [
        Assumption(
            key="horizon_days",
            label="Time horizon",
            value=query.horizon_days,
            unit="days",
            value_type=ValueType.SCENARIO,
            source="user",
        ),
        Assumption(
            key="alpha",
            label="Boarding while infectious (relative)",
            value=alpha,
            value_type=ValueType.SCENARIO,
            source="user" if query.alpha is not None else f"{profile.label} profile default",
            note=profile.alpha.note if query.alpha is None else None,
        ),
        Assumption(
            key="sigma",
            label="Screening and border effectiveness",
            value=query.sigma,
            value_type=ValueType.SCENARIO,
            source="user",
            note="0 means no confirmed measure, which is the default.",
        ),
        Assumption(
            key="underreporting",
            label="Under-reporting multiplier",
            value=(
                f"{query.underreporting_low:g}x / {query.underreporting_central:g}x / "
                f"{query.underreporting_high:g}x"
            ),
            value_type=ValueType.SCENARIO,
            source="user",
            note="Low / central / high. No measured value exists for a live outbreak.",
        ),
        Assumption(
            key="passenger_scale",
            label="Passenger volume scale",
            value=query.passenger_scale,
            value_type=ValueType.SCENARIO,
            source="user",
        ),
        Assumption(
            key="reproduction_number",
            label="Reproduction number R",
            value=r_central,
            value_type=ValueType.SCENARIO,
            source=(
                "user"
                if query.reproduction_number is not None
                else f"{profile.label} profile default"
            ),
            note=profile.reproduction_number.note if query.reproduction_number is None else None,
        ),
        Assumption(
            key="dispersion_k",
            label="Cluster dispersion k",
            value=k_central,
            value_type=ValueType.SCENARIO,
            source="user" if query.dispersion_k is not None else f"{profile.label} profile default",
            note=profile.dispersion_k.note if query.dispersion_k is None else None,
        ),
        Assumption(
            key="infectious_period_days",
            label="Infectious period",
            value=profile.infectious_period_days,
            unit="days",
            value_type=ValueType.SCENARIO,
            source=f"{profile.label} profile default",
        ),
    ]

    freshness: list[DataFreshness] = []
    for version in reference_repo.active_dataset_versions(session):
        freshness.append(
            DataFreshness(
                source=version.source_name,
                retrieved_at=version.retrieved_at,
                record_count=version.record_count,
                status="ok",
            )
        )
    run = outbreak_repo.latest_run(session)
    if run is not None:
        freshness.append(
            DataFreshness(
                source="WHO Disease Outbreak News (last ingestion)",
                retrieved_at=run.finished_at or run.started_at,
                record_count=run.records_created + run.records_updated,
                status="ok" if run.status == "succeeded" else "degraded",
                detail=f"mode={run.mode}, status={run.status}",
            )
        )

    return RiskResponse(
        destination_iso3=iso3,
        destination_name=name,
        pathogen=PathogenSummary(
            key=matched_key or profile.key,
            label=profile.label,
            disease_label=_disease_name(session, query, matched_key or profile.key, iso3),
            confidence=profile.confidence.value,
            establishment_estimable=profile.establishment_estimable,
            establishment_note=profile.establishment_note,
            references=list(profile.references),
        ),
        horizon_days=query.horizon_days,
        computed_at=utc_now(),
        model_version=MODEL_VERSION,
        presence=presence,
        importation=importation,
        establishment=establishment,
        scenario_markers=markers,
        assumptions=assumptions,
        warnings=warnings,
        data=freshness,
        disclaimer=DISCLAIMER,
    )
