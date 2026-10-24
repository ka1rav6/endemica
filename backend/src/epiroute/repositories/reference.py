from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from epiroute.db.models import Country, CountryFlow, DatasetVersion, GravityModelFit
from epiroute.schemas.common import ValueType


@dataclass(frozen=True, slots=True)
class FlowRow:
    origin_iso3: str
    dest_iso3: str
    passengers_per_day: float
    value_type: ValueType
    source: str
    reference_period: str | None
    uncertainty_factor: float | None
    direct_route_count: int | None


def get_country(session: Session, iso3: str) -> Country | None:
    return session.get(Country, iso3.upper())


def list_countries(session: Session) -> list[Country]:
    return list(session.scalars(select(Country).order_by(Country.name)))


def inbound_flows(session: Session, dest_iso3: str) -> list[FlowRow]:
    rows = session.scalars(select(CountryFlow).where(CountryFlow.dest_iso3 == dest_iso3.upper()))
    return [_to_row(row) for row in rows]


def outbound_flows(session: Session, origin_iso3: str) -> list[FlowRow]:
    rows = session.scalars(
        select(CountryFlow).where(CountryFlow.origin_iso3 == origin_iso3.upper())
    )
    return [_to_row(row) for row in rows]


def flows_between(session: Session, origins: list[str], dest_iso3: str) -> dict[str, FlowRow]:
    if not origins:
        return {}
    rows = session.scalars(
        select(CountryFlow).where(
            CountryFlow.dest_iso3 == dest_iso3.upper(),
            CountryFlow.origin_iso3.in_([o.upper() for o in origins]),
        )
    )
    return {row.origin_iso3: _to_row(row) for row in rows}


def all_flows(session: Session) -> list[FlowRow]:
    return [_to_row(row) for row in session.scalars(select(CountryFlow))]


def active_gravity_fit(session: Session) -> GravityModelFit | None:
    return session.scalar(
        select(GravityModelFit)
        .where(GravityModelFit.is_active.is_(True))
        .order_by(GravityModelFit.fitted_at.desc())
        .limit(1)
    )


def active_dataset_versions(session: Session) -> list[DatasetVersion]:
    return list(
        session.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.is_active.is_(True))
            .order_by(DatasetVersion.dataset)
        )
    )


def flow_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(CountryFlow.value_type, func.count()).group_by(CountryFlow.value_type)
    )
    return {str(value_type.value): count for value_type, count in rows}


def _to_row(row: CountryFlow) -> FlowRow:
    return FlowRow(
        origin_iso3=row.origin_iso3,
        dest_iso3=row.dest_iso3,
        passengers_per_day=row.passengers_per_day,
        value_type=row.value_type,
        source=row.source,
        reference_period=row.reference_period,
        uncertainty_factor=row.uncertainty_factor,
        direct_route_count=row.direct_route_count,
    )
