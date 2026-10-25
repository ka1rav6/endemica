"""The vocabulary shared by every Endemica value: provenance and value type.

AGENTS.md section 9.4 requires that the API, UI and documentation consistently
distinguish how a number came to exist. That distinction is enforced here: a
numeric result is published as a :class:`Quantity` or :class:`BandedQuantity`
which cannot be constructed without stating its :class:`ValueType`, and a
missing value is represented by ``value=None`` plus an
:class:`UnavailableReason` — never by zero.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ValueType(StrEnum):
    """How a published number was produced.

    The five categories are mutually exclusive and are surfaced verbatim in the
    API and the UI legend.

    Attributes:
        OBSERVED: Directly reported or measured by an identified source, used
            without transformation beyond unit conversion and ISO normalisation.
        ESTIMATED: Derived from observations by a documented procedure that
            introduces assumptions (an under-reporting multiplier, a gravity
            model prediction).
        MODELLED: Produced by an explicit mathematical model from other inputs
            (the Poisson importation probability, the branching-process
            establishment probability).
        SCENARIO: Produced under user-selected or deliberately extreme
            assumptions. Scenario values answer "what if", not "what is".
        UNKNOWN: Inputs were insufficient to produce a meaningful value.
    """

    OBSERVED = "observed"
    ESTIMATED = "estimated"
    MODELLED = "modelled"
    SCENARIO = "scenario"
    UNKNOWN = "unknown"


class UnavailableReason(StrEnum):
    """Why a value could not be produced.

    Attached to every null numeric field so the UI can explain the gap instead
    of showing a blank or a zero.
    """

    NO_LOCAL_CASE_DATA = "no_local_case_data"
    NO_PASSENGER_DATA = "no_passenger_data"
    NO_POPULATION_DATA = "no_population_data"
    NO_PREVALENCE_DATA = "no_prevalence_data"
    NO_ACTIVE_OUTBREAK = "no_active_outbreak"
    PARAMETER_NOT_ESTIMABLE = "parameter_not_estimable"
    MODEL_NOT_APPLICABLE = "model_not_applicable"
    SUBTHRESHOLD_TRANSMISSION = "subthreshold_transmission"
    NUMERICAL_FAILURE = "numerical_failure"
    NOT_IMPLEMENTED = "not_implemented"


class ExtractionStatus(StrEnum):
    """Outcome of extracting structured fields from a source document."""

    VERIFIED = "verified"
    """Every extracted number was found verbatim in the retrieved source text."""

    UNVERIFIED = "unverified"
    """Extraction produced values that could not be grounded in the source text.

    Such records are displayed with their source link but are excluded from
    every model input.
    """

    PARTIAL = "partial"
    """Some fields were grounded and others were not; only grounded fields are used."""

    FAILED = "failed"
    """Extraction did not complete. The source link is still shown."""

    NOT_ATTEMPTED = "not_attempted"
    """The record came from a structured API field, so no extraction was needed."""


class ExtractionMethod(StrEnum):
    """Which mechanism produced a record's structured fields."""

    WHO_API_FIELD = "who_api_field"
    """Taken from a structured field of the WHO Disease Outbreak News API."""

    DETERMINISTIC_PARSER = "deterministic_parser"
    """Endemica's own rule-based parser over the report narrative."""

    TINYFISH_AGENT = "tinyfish_agent"
    """TinyFish Agent structured extraction."""

    TINYFISH_FETCH = "tinyfish_fetch"
    """TinyFish Fetch text, parsed by the deterministic parser."""


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
"""A probability in [0, 1]. Validated at the schema boundary."""


class Provenance(BaseModel):
    """Where a record came from and when, as required by AGENTS.md section 9.3."""

    model_config = ConfigDict(frozen=True)

    source_name: str = Field(description="Publisher, e.g. 'WHO Disease Outbreak News'.")
    source_url: HttpUrl | None = Field(
        default=None, description="Canonical public URL of the source document."
    )
    source_identifier: str | None = Field(
        default=None, description="Publisher's own identifier, e.g. the WHO DON id."
    )
    published_at: datetime | None = Field(
        default=None, description="Publication time stated by the source (UTC)."
    )
    retrieved_at: datetime = Field(description="When Endemica retrieved the document (UTC).")
    extraction_method: ExtractionMethod | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.NOT_ATTEMPTED
    extraction_run_id: str | None = Field(
        default=None, description="Identifier of the ingestion run that produced this record."
    )
    license_note: str | None = Field(
        default=None, description="Licensing or reuse condition recorded for the source."
    )


class Quantity(BaseModel):
    """A single number published together with how it was produced.

    ``value`` is ``None`` exactly when the inputs were insufficient; in that
    case ``value_type`` is :attr:`ValueType.UNKNOWN` and ``unavailable_reason``
    explains the gap. This invariant is enforced, which is what prevents a
    missing input from being rendered as ``0``.
    """

    model_config = ConfigDict(frozen=True)

    value: float | None
    value_type: ValueType
    unit: str | None = Field(default=None, description="Unit of `value`, e.g. 'passengers/day'.")
    unavailable_reason: UnavailableReason | None = None
    note: str | None = Field(default=None, description="Short human-readable qualifier.")

    @model_validator(mode="after")
    def _check_missing_value_contract(self) -> Self:
        """Enforce the "no silent zeros" rule in both directions."""
        if self.value is None:
            if self.value_type is not ValueType.UNKNOWN:
                msg = "a Quantity without a value must have value_type 'unknown'"
                raise ValueError(msg)
            if self.unavailable_reason is None:
                msg = "a Quantity without a value must state an unavailable_reason"
                raise ValueError(msg)
        elif self.value_type is ValueType.UNKNOWN:
            msg = "a Quantity with a value must not have value_type 'unknown'"
            raise ValueError(msg)
        return self

    @classmethod
    def unavailable(cls, reason: UnavailableReason, *, note: str | None = None) -> Quantity:
        """Build the "not estimable" form of a quantity."""
        return cls(value=None, value_type=ValueType.UNKNOWN, unavailable_reason=reason, note=note)

    @classmethod
    def of(
        cls,
        value: float,
        value_type: ValueType,
        *,
        unit: str | None = None,
        note: str | None = None,
    ) -> Quantity:
        """Build an available quantity."""
        return cls(value=value, value_type=value_type, unit=unit, note=note)


class BandedQuantity(BaseModel):
    """A central value with a low and a high bound.

    The bounds are *scenario bounds*: they come from re-running the model at
    the low and high ends of its uncertain inputs. They are not statistically
    calibrated confidence intervals, and :attr:`band_basis` says so in words
    that the UI displays verbatim (AGENTS.md section 10.2).
    """

    model_config = ConfigDict(frozen=True)

    low: float | None
    central: float | None
    high: float | None
    value_type: ValueType
    unit: str | None = None
    band_basis: str | None = Field(
        default=None,
        description=(
            "How the bounds were produced, e.g. 'scenario range: under-reporting "
            "2x-10x'. Not a confidence interval."
        ),
    )
    unavailable_reason: UnavailableReason | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_ordering_and_missing_contract(self) -> Self:
        """Require ``low <= central <= high`` and the missing-value contract."""
        present = [v for v in (self.low, self.central, self.high) if v is not None]
        if not present:
            if self.value_type is not ValueType.UNKNOWN:
                msg = "a BandedQuantity without values must have value_type 'unknown'"
                raise ValueError(msg)
            if self.unavailable_reason is None:
                msg = "a BandedQuantity without values must state an unavailable_reason"
                raise ValueError(msg)
            return self
        if self.value_type is ValueType.UNKNOWN:
            msg = "a BandedQuantity with values must not have value_type 'unknown'"
            raise ValueError(msg)
        if self.low is not None and self.central is not None and self.low > self.central:
            msg = f"band low ({self.low}) exceeds central ({self.central})"
            raise ValueError(msg)
        if self.central is not None and self.high is not None and self.central > self.high:
            msg = f"band central ({self.central}) exceeds high ({self.high})"
            raise ValueError(msg)
        if (
            self.low is not None
            and self.high is not None
            and self.central is None
            and self.low > self.high
        ):
            msg = f"band low ({self.low}) exceeds high ({self.high})"
            raise ValueError(msg)
        return self

    @classmethod
    def unavailable(cls, reason: UnavailableReason, *, note: str | None = None) -> BandedQuantity:
        """Build the "not estimable" form of a banded quantity."""
        return cls(
            low=None,
            central=None,
            high=None,
            value_type=ValueType.UNKNOWN,
            unavailable_reason=reason,
            note=note,
        )


class Assumption(BaseModel):
    """One assumption behind a published value, shown in the UI next to it.

    Every model response carries the full list, so a user can see which numbers
    are inputs they chose and which are defaults Endemica supplied.
    """

    model_config = ConfigDict(frozen=True)

    key: str = Field(description="Stable machine name, e.g. 'alpha'.")
    label: str = Field(description="Short human label, e.g. 'Boarding while infectious'.")
    value: float | str | bool | None
    unit: str | None = None
    value_type: ValueType = ValueType.SCENARIO
    source: str = Field(
        description=(
            "Where this value came from: 'user', 'pathogen profile default', "
            "or a literature citation."
        )
    )
    note: str | None = None


class ResponseWarning(BaseModel):
    """A caveat attached to a response.

    Collected into a ``warnings`` list that the UI renders next to the numbers,
    so a limitation travels with the value it qualifies instead of living only
    in the documentation.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    severity: Annotated[str, Field(pattern="^(info|caution|important)$")] = "caution"


class DataFreshness(BaseModel):
    """Age and status of one data source backing a response."""

    model_config = ConfigDict(frozen=True)

    source: str
    retrieved_at: datetime | None = None
    record_count: int | None = None
    is_stale: bool = Field(
        default=False, description="True when the data is older than its documented refresh window."
    )
    status: Annotated[str, Field(pattern="^(ok|stale|missing|degraded)$")] = "ok"
    detail: str | None = None
