"""Incidence is differenced inside one source and one disease."""

from __future__ import annotations

from datetime import UTC, datetime

from endemica.repositories.outbreaks import CumulativePoint, choose_single_series


def _point(day: int, cases: int, source: str, disease: str) -> CumulativePoint:
    return CumulativePoint(
        published_at=datetime(2026, 1, day, tzinfo=UTC),
        cases_confirmed=cases,
        deaths=None,
        report_identifier=f"{source}-{disease}-{day}",
        report_url="https://example.test",
        source_name=source,
        disease_id=disease,
    )


def test_the_newest_source_is_used_and_the_other_is_not_mixed_in() -> None:
    who = [_point(1, 10, "who_don", "measles"), _point(10, 40, "who_don", "measles")]
    ecdc = [_point(12, 5, "ecdc_cdtr", "covid")]
    chosen = choose_single_series({("who_don", "measles"): who, ("ecdc_cdtr", "covid"): ecdc})
    assert [point.cases_confirmed for point in chosen] == [5]
    assert chosen[0].source_name == "ecdc_cdtr"
