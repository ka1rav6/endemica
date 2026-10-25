"""The "no silent zeros" contract on Quantity and BandedQuantity.

These are the guards that stop a missing input from being rendered as a real
number anywhere in the API (AGENTS.md section 9.4).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from endemica.schemas.common import (
    BandedQuantity,
    Probability,
    Quantity,
    UnavailableReason,
    ValueType,
)


class TestQuantity:
    def test_available_quantity_round_trips(self) -> None:
        q = Quantity.of(2.5, ValueType.MODELLED, unit="arrivals/day")
        assert q.value == 2.5
        assert q.value_type is ValueType.MODELLED
        assert q.unavailable_reason is None

    def test_unavailable_quantity_states_a_reason(self) -> None:
        q = Quantity.unavailable(UnavailableReason.NO_PASSENGER_DATA)
        assert q.value is None
        assert q.value_type is ValueType.UNKNOWN
        assert q.unavailable_reason is UnavailableReason.NO_PASSENGER_DATA

    def test_missing_value_without_unknown_type_is_rejected(self) -> None:
        """A null value must not be published as if it were modelled."""
        with pytest.raises(ValidationError, match="must have value_type 'unknown'"):
            Quantity(value=None, value_type=ValueType.MODELLED)

    def test_missing_value_without_a_reason_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must state an unavailable_reason"):
            Quantity(value=None, value_type=ValueType.UNKNOWN)

    def test_present_value_with_unknown_type_is_rejected(self) -> None:
        """The inverse mistake: a real number labelled as not estimable."""
        with pytest.raises(ValidationError, match="must not have value_type 'unknown'"):
            Quantity(value=0.3, value_type=ValueType.UNKNOWN)

    def test_zero_is_a_legitimate_observed_value(self) -> None:
        """Zero must stay expressible: 'zero reported cases' is information."""
        q = Quantity.of(0.0, ValueType.OBSERVED, unit="cases")
        assert q.value == 0.0
        assert q.unavailable_reason is None

    def test_quantity_is_immutable(self) -> None:
        q = Quantity.of(1.0, ValueType.OBSERVED)
        with pytest.raises(ValidationError):
            q.value = 2.0


class TestBandedQuantity:
    def test_ordered_band_is_accepted(self) -> None:
        b = BandedQuantity(
            low=0.1,
            central=0.4,
            high=0.8,
            value_type=ValueType.MODELLED,
            band_basis="scenario range: under-reporting 2x-10x",
        )
        assert (b.low, b.central, b.high) == (0.1, 0.4, 0.8)

    @pytest.mark.parametrize(
        ("low", "central", "high"),
        [(0.5, 0.2, 0.8), (0.1, 0.9, 0.4), (0.9, 0.5, 0.1)],
    )
    def test_misordered_band_is_rejected(self, low: float, central: float, high: float) -> None:
        with pytest.raises(ValidationError, match="exceeds"):
            BandedQuantity(low=low, central=central, high=high, value_type=ValueType.MODELLED)

    def test_misordered_band_without_central_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds"):
            BandedQuantity(low=0.9, central=None, high=0.1, value_type=ValueType.MODELLED)

    def test_degenerate_band_is_accepted(self) -> None:
        """Equal bounds are valid: they mean the inputs carry no uncertainty."""
        b = BandedQuantity(low=0.3, central=0.3, high=0.3, value_type=ValueType.MODELLED)
        assert b.low == b.high

    def test_unavailable_band_states_a_reason(self) -> None:
        b = BandedQuantity.unavailable(UnavailableReason.NO_PREVALENCE_DATA)
        assert (b.low, b.central, b.high) == (None, None, None)
        assert b.value_type is ValueType.UNKNOWN

    def test_empty_band_without_a_reason_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must state an unavailable_reason"):
            BandedQuantity(low=None, central=None, high=None, value_type=ValueType.UNKNOWN)

    def test_empty_band_with_a_non_unknown_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must have value_type 'unknown'"):
            BandedQuantity(low=None, central=None, high=None, value_type=ValueType.SCENARIO)


class TestProbabilityType:
    @pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
    def test_out_of_range_probability_is_rejected(self, bad: float) -> None:
        from pydantic import BaseModel

        class M(BaseModel):
            p: Probability

        with pytest.raises(ValidationError):
            M(p=bad)

    @pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
    def test_boundary_probabilities_are_accepted(self, good: float) -> None:
        from pydantic import BaseModel

        class M(BaseModel):
            p: Probability

        assert M(p=good).p == good


def test_value_type_names_are_the_documented_strings() -> None:
    """The UI legend and docs quote these exact strings; they are contract."""
    assert [v.value for v in ValueType] == [
        "observed",
        "estimated",
        "modelled",
        "scenario",
        "unknown",
    ]
