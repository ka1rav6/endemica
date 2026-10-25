"""Prevalence estimation from reported case counts.

The emphasis is on the refusal paths: the estimator must decline rather than
guess when the data cannot support an estimate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from endemica.core.errors import ModelInputError
from endemica.epidemiology.prevalence import (
    DEFAULT_UNDERREPORTING,
    MAX_PLAUSIBLE_PREVALENCE,
    PrevalenceEstimate,
    PrevalenceMethod,
    PrevalenceUnavailable,
    ReportedCount,
    estimate_from_incidence,
    estimate_from_single_report,
    prevalence_from_series,
)

NOW = datetime(2026, 10, 24, tzinfo=UTC)
POP = 10_000_000


def _days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


class TestIncidenceDifferencing:
    def test_estimate_matches_the_formula_by_hand(self) -> None:
        """140 new cases over 14 days = 10/day; x 7-day period x 4 = 280."""
        result = estimate_from_incidence(
            100,
            _days_ago(18),
            240,
            _days_ago(4),
            population=POP,
            infectious_period_days=7.0,
            underreporting=(2.0, 4.0, 10.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.INCIDENCE_DIFFERENCE
        assert result.infectious_cases_central == pytest.approx(280.0)
        assert result.central == pytest.approx(280.0 / POP)
        assert result.low == pytest.approx(140.0 / POP)
        assert result.high == pytest.approx(700.0 / POP)

    def test_band_is_ordered_and_scales_with_the_multiplier(self) -> None:
        result = estimate_from_incidence(
            0,
            _days_ago(14),
            100,
            NOW,
            population=POP,
            infectious_period_days=5.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.low < result.central < result.high
        assert result.high / result.low == pytest.approx(
            DEFAULT_UNDERREPORTING[2] / DEFAULT_UNDERREPORTING[0]
        )

    def test_a_stale_report_is_declined(self) -> None:
        """An outbreak nobody has reported on for months may be over."""
        result = estimate_from_incidence(
            100,
            _days_ago(200),
            300,
            _days_ago(120),
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "report_too_old"

    def test_no_new_cases_is_declined(self) -> None:
        """Flat cumulative counts are not evidence of current transmission."""
        result = estimate_from_incidence(
            500,
            _days_ago(20),
            500,
            _days_ago(2),
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "no_new_cases"

    def test_downward_revision_is_declined(self) -> None:
        """Reclassification happens; it carries no incidence signal."""
        result = estimate_from_incidence(
            500,
            _days_ago(20),
            400,
            _days_ago(2),
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "counts_revised_downwards"

    def test_identical_dates_are_declined(self) -> None:
        result = estimate_from_incidence(
            100,
            _days_ago(5),
            200,
            _days_ago(5),
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "no_elapsed_time"

    def test_implausible_estimate_is_clamped_and_flagged(self) -> None:
        """A mis-parsed count must not drive the whole model."""
        result = estimate_from_incidence(
            0,
            _days_ago(2),
            9_000_000,
            _days_ago(1),
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.clamped is True
        assert result.high == MAX_PLAUSIBLE_PREVALENCE
        assert any("clamped" in c for c in result.caveats)

    def test_result_carries_its_caveats(self) -> None:
        result = estimate_from_incidence(
            10,
            _days_ago(10),
            50,
            _days_ago(1),
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.caveats
        assert any("not infections" in c for c in result.caveats)


class TestSingleReportFallback:
    def test_estimate_matches_the_formula_by_hand(self) -> None:
        """1000 cases x (7/70 active fraction) x 4 = 400."""
        result = estimate_from_single_report(
            1000,
            _days_ago(4),
            population=POP,
            infectious_period_days=7.0,
            outbreak_age_days=70.0,
            underreporting=(2.0, 4.0, 10.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.RECENT_WINDOW
        assert result.infectious_cases_central == pytest.approx(400.0)

    def test_unknown_age_uses_the_active_window(self) -> None:
        """No start date still yields an estimate, over the 90-day active window."""
        result = estimate_from_single_report(
            1000,
            _days_ago(4),
            population=POP,
            infectious_period_days=7.0,
            outbreak_age_days=None,
            underreporting=(1.0, 1.0, 1.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.infectious_cases_central == pytest.approx(1000 * 7 / 90)
        assert any("assumed" in caveat for caveat in result.caveats)

    def test_outbreak_younger_than_the_infectious_period_has_no_recoveries(self) -> None:
        """The active fraction is floored at 1, never above it."""
        result = estimate_from_single_report(
            100,
            _days_ago(1),
            population=POP,
            infectious_period_days=7.0,
            outbreak_age_days=2.0,
            underreporting=(1.0, 1.0, 1.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.infectious_cases_central == pytest.approx(100.0)

    def test_older_outbreak_gives_a_lower_estimate(self) -> None:
        def estimate(age: float) -> float:
            r = estimate_from_single_report(
                1000,
                _days_ago(1),
                population=POP,
                infectious_period_days=7.0,
                outbreak_age_days=age,
                underreporting=(1.0, 1.0, 1.0),
                as_of=NOW,
            )
            assert isinstance(r, PrevalenceEstimate)
            return r.central

        assert estimate(7.0) > estimate(30.0) > estimate(365.0)

    def test_zero_cases_is_declined_not_zero_prevalence(self) -> None:
        """A report naming a country without a count is not 'no cases'."""
        result = estimate_from_single_report(
            0, _days_ago(1), population=POP, infectious_period_days=7.0, as_of=NOW
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "no_reported_cases"

    def test_a_stale_report_is_declined(self) -> None:
        result = estimate_from_single_report(
            1000, _days_ago(120), population=POP, infectious_period_days=7.0, as_of=NOW
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "report_too_old"

    def test_fallback_is_flagged_as_weaker(self) -> None:
        result = estimate_from_single_report(
            100,
            _days_ago(1),
            population=POP,
            infectious_period_days=7.0,
            outbreak_age_days=30.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert any("weaker" in c for c in result.caveats)


class TestSeriesSelection:
    """The series chooser must not let the weak estimator overrule the strong one."""

    def test_two_increasing_reports_use_incidence(self) -> None:
        result = prevalence_from_series(
            [
                ReportedCount(_days_ago(18), 100),
                ReportedCount(_days_ago(4), 240),
            ],
            population=POP,
            infectious_period_days=7.0,
            underreporting=(2.0, 4.0, 10.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.INCIDENCE_DIFFERENCE
        assert result.infectious_cases_central == pytest.approx(280.0)

    def test_flat_series_is_not_replaced_by_the_cumulative_guess(self) -> None:
        """500 cases twice is not evidence that 500 people are still infectious."""
        result = prevalence_from_series(
            [
                ReportedCount(_days_ago(20), 500),
                ReportedCount(_days_ago(2), 500),
            ],
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "no_new_cases"

    def test_downward_revision_is_not_replaced_by_the_cumulative_guess(self) -> None:
        result = prevalence_from_series(
            [
                ReportedCount(_days_ago(20), 500),
                ReportedCount(_days_ago(2), 400),
            ],
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceUnavailable)
        assert result.reason == "counts_revised_downwards"

    def test_a_duplicate_timestamp_does_not_hide_an_earlier_change(self) -> None:
        result = prevalence_from_series(
            [
                ReportedCount(_days_ago(18), 100),
                ReportedCount(_days_ago(4), 240),
                ReportedCount(_days_ago(4), 240),
            ],
            population=POP,
            infectious_period_days=7.0,
            underreporting=(2.0, 4.0, 10.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.INCIDENCE_DIFFERENCE
        assert result.infectious_cases_central == pytest.approx(280.0)

    def test_one_report_without_a_start_date_still_estimates(self) -> None:
        """1000 cases, assumed age 90 days, D = 7, u = 4."""
        result = prevalence_from_series(
            [ReportedCount(_days_ago(4), 1000)],
            population=POP,
            infectious_period_days=7.0,
            underreporting=(2.0, 4.0, 10.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.RECENT_WINDOW
        assert result.infectious_cases_central == pytest.approx(1000 * 7 / 90 * 4)

    def test_one_report_with_a_stated_start_uses_the_uniform_window(self) -> None:
        """1000 cases over 70 days, 7-day infectious period, u = 4 → 400."""
        result = prevalence_from_series(
            [
                ReportedCount(
                    _days_ago(4),
                    1000,
                    outbreak_started_on=_days_ago(74).date(),
                )
            ],
            population=POP,
            infectious_period_days=7.0,
            underreporting=(2.0, 4.0, 10.0),
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.RECENT_WINDOW
        assert result.infectious_cases_central == pytest.approx(400.0)


class TestValidation:
    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_population_is_rejected(self, bad: int) -> None:
        with pytest.raises(ModelInputError, match="population"):
            estimate_from_single_report(
                10, NOW, population=bad, infectious_period_days=7.0, as_of=NOW
            )

    def test_negative_cases_are_rejected(self) -> None:
        with pytest.raises(ModelInputError, match="cumulative_cases"):
            estimate_from_single_report(
                -5, NOW, population=POP, infectious_period_days=7.0, as_of=NOW
            )

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_invalid_infectious_period_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="infectious_period_days"):
            estimate_from_single_report(
                10, NOW, population=POP, infectious_period_days=bad, as_of=NOW
            )

    def test_underreporting_below_one_is_rejected(self) -> None:
        """u < 1 would mean over-reporting, which this model does not represent."""
        with pytest.raises(ModelInputError, match=r"at least 1\.0"):
            estimate_from_single_report(
                10,
                NOW,
                population=POP,
                infectious_period_days=7.0,
                underreporting=(0.5, 1.0, 2.0),
                as_of=NOW,
            )

    def test_misordered_underreporting_is_rejected(self) -> None:
        with pytest.raises(ModelInputError, match="ordered"):
            estimate_from_single_report(
                10,
                NOW,
                population=POP,
                infectious_period_days=7.0,
                underreporting=(10.0, 2.0, 4.0),
                as_of=NOW,
            )


class TestAsOfCutoff:
    def test_a_report_after_the_forecast_date_is_excluded(self) -> None:
        result = prevalence_from_series(
            [
                ReportedCount(_days_ago(10), 100),
                ReportedCount(NOW + timedelta(days=3), 400),
            ],
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.reported_cases == 100

    def test_reports_less_than_a_day_apart_are_not_differenced(self) -> None:
        result = prevalence_from_series(
            [
                ReportedCount(_days_ago(5), 100),
                ReportedCount(_days_ago(5) + timedelta(hours=6), 180),
            ],
            population=POP,
            infectious_period_days=7.0,
            as_of=NOW,
        )
        assert isinstance(result, PrevalenceEstimate)
        assert result.method is PrevalenceMethod.RECENT_WINDOW
