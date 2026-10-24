"""Splitting one country's reports into separate outbreaks.

Cumulative counts only rise inside a single outbreak. A country that reports
the same disease again years later restarts from a low figure, and carrying the
earlier epidemic's peak across that boundary makes the current outbreak look
like it has no new cases, which silently removes it from every estimate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from epiroute.repositories.outbreaks import CumulativePoint, _latest_episode, _running_max


def _point(day: datetime, cases: int | None, deaths: int | None = None) -> CumulativePoint:
    return CumulativePoint(
        published_at=day,
        cases_confirmed=cases,
        deaths=deaths,
        report_identifier=f"DON-{day.date()}",
        report_url="https://example.invalid/report",
    )


START = datetime(2026, 1, 1, tzinfo=UTC)


class TestWithinOneOutbreak:
    def test_counts_only_ever_rise(self) -> None:
        series = _running_max(
            [
                _point(START, 100),
                _point(START + timedelta(days=14), 250),
                _point(START + timedelta(days=28), 400),
            ]
        )
        assert [p.cases_confirmed for p in series] == [100, 250, 400]

    def test_a_report_with_no_count_keeps_the_running_total(self) -> None:
        series = _running_max(
            [
                _point(START, 100),
                _point(START + timedelta(days=14), None),
                _point(START + timedelta(days=28), 180),
            ]
        )
        assert [p.cases_confirmed for p in series] == [100, 100, 180]

    def test_a_small_downward_revision_does_not_restart(self) -> None:
        # A few per cent lower is the source correcting itself, not a new outbreak.
        series = _running_max(
            [
                _point(START, 1000),
                _point(START + timedelta(days=14), 970),
                _point(START + timedelta(days=28), 1100),
            ]
        )
        assert [p.cases_confirmed for p in series] == [1000, 1000, 1100]


class TestAcrossOutbreaks:
    def test_a_far_lower_count_starts_a_new_outbreak(self) -> None:
        series = _running_max(
            [
                _point(START, 57_197),
                _point(START + timedelta(days=30), 3626),
                _point(START + timedelta(days=60), 9704),
            ]
        )
        assert [p.cases_confirmed for p in series] == [57_197, 3626, 9704]

    def test_the_current_outbreak_shows_new_cases(self) -> None:
        """The regression: incidence was zero, so the origin was dropped."""
        series = _running_max(
            [
                _point(START, 57_197),
                _point(START + timedelta(days=30), 8728),
                _point(START + timedelta(days=45), 9704),
            ]
        )
        assert series[-1].cases_confirmed > series[-2].cases_confirmed

    def test_a_year_long_gap_starts_a_new_outbreak(self) -> None:
        # Counts keep rising, but the reports are two separate episodes.
        series = _running_max(
            [
                _point(START, 400),
                _point(START + timedelta(days=800), 600),
            ]
        )
        assert [p.cases_confirmed for p in series] == [400, 600]
        assert series[-1].cases_confirmed == 600

    def test_only_the_latest_episode_is_differenced(self) -> None:
        episode = _latest_episode(
            [
                _point(START, 400),
                _point(START + timedelta(days=800), 600),
            ]
        )
        assert [point.cases_confirmed for point in episode] == [600]

    def test_deaths_restart_with_their_outbreak(self) -> None:
        series = _running_max(
            [
                _point(START, 57_197, 2300),
                _point(START + timedelta(days=30), 3626, 120),
            ]
        )
        assert [p.deaths for p in series] == [2300, 120]
