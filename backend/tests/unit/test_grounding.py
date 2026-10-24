"""The validation gate.

The decisive test is :class:`TestAgainstRealAgentResponse`, which runs the gate
over a genuine TinyFish Agent response captured on 24 Oct 2026. That response
contains fabricated numbers, numbers borrowed from other sentences, a
recoveries figure labelled as suspected cases, a swapped cases/deaths pair and
a vaccination-coverage ratio read as a case count. Every one must be rejected,
and the twelve correct values must survive — verified by hand against the
source text and asserted here so a change in the gate cannot silently loosen
it.
"""

from __future__ import annotations

from typing import Any

import pytest

from epiroute.ingestion.grounding import (
    LABEL_WINDOW,
    Verdict,
    check_evidence_grounded,
    check_label_proximity,
    ground_record,
    normalise_text,
    number_variants,
)


class TestNormalisation:
    def test_whitespace_runs_collapse(self) -> None:
        assert normalise_text("a  \n\t b") == "a b"

    def test_markdown_emphasis_is_removed(self) -> None:
        """Fetch returns markdown while the WHO API returns HTML."""
        assert normalise_text("the **epicentre**") == "the epicentre"
        assert normalise_text("*italic* and __bold__") == "italic and bold"

    def test_case_is_folded(self) -> None:
        assert normalise_text("ITURI") == normalise_text("ituri")

    @pytest.mark.parametrize("space", [" ", " ", " "])
    def test_exotic_spaces_become_ordinary_ones(self, space: str) -> None:
        assert normalise_text(f"1{space}234") == "1 234"

    def test_full_width_digits_become_ascii(self) -> None:
        assert normalise_text("１２３") == "123"


class TestNumberVariants:
    def test_short_numbers_have_one_form(self) -> None:
        assert number_variants(42) == ("42",)
        assert number_variants(999) == ("999",)

    def test_thousands_separators_are_covered(self) -> None:
        variants = number_variants(1234)
        assert "1234" in variants
        assert "1,234" in variants
        assert "1.234" in variants
        assert "1 234" in variants
        assert "1 234" in variants

    def test_millions_group_in_threes(self) -> None:
        assert "1,234,567" in number_variants(1234567)


class TestNumberBoundaries:
    """A substring match would ground almost anything in a numeric narrative."""

    SOURCE = "Ituri: 7040 confirmed cases, 3271 deaths, 1,234 contacts, 1 234 samples."

    @pytest.mark.parametrize("value", [7040, 3271, 1234])
    def test_whole_numbers_are_found(self, value: int) -> None:
        report = ground_record({"deaths": value}, evidence=self.SOURCE, source_text=self.SOURCE)
        assert report.fields[0].verdict is not Verdict.NOT_IN_SOURCE

    @pytest.mark.parametrize("value", [76, 704, 234, 27, 1])
    def test_fragments_of_longer_numbers_are_not_found(self, value: int) -> None:
        """76 must not match inside 7040, nor 234 inside 1,234."""
        report = ground_record({"deaths": value}, evidence=self.SOURCE, source_text=self.SOURCE)
        assert report.fields[0].verdict is Verdict.NOT_IN_SOURCE

    def test_an_ordinary_space_before_a_number_is_fine(self) -> None:
        """A space is a thousands separator *and* a word break; both must work."""
        source = "There were 27 deaths."
        report = ground_record({"deaths": 27}, evidence=source, source_text=source)
        assert report.fields[0].is_usable


class TestEvidenceGrounding:
    SOURCE = "Elsewhere, Tshopo has recorded 76 cases and 27 deaths in the period."

    def test_verbatim_quote_is_grounded(self) -> None:
        grounded, detail = check_evidence_grounded("Tshopo has recorded 76 cases", self.SOURCE)
        assert grounded
        assert "verbatim" in detail

    def test_truncated_quote_with_an_added_full_stop_is_grounded(self) -> None:
        """A real extractor behaviour; the words are all present and in order."""
        grounded, detail = check_evidence_grounded("Tshopo has recorded 76 cases.", self.SOURCE)
        assert grounded
        assert "truncated" in detail

    def test_invented_wording_is_rejected(self) -> None:
        grounded, _ = check_evidence_grounded(
            "Tshopo has recorded 76 fatal cases overall.", self.SOURCE
        )
        assert not grounded

    def test_reordered_wording_is_rejected(self) -> None:
        grounded, _ = check_evidence_grounded("76 cases have been recorded by Tshopo.", self.SOURCE)
        assert not grounded

    @pytest.mark.parametrize("evidence", [None, "", "   "])
    def test_missing_quote_is_rejected(self, evidence: str | None) -> None:
        grounded, detail = check_evidence_grounded(evidence, self.SOURCE)
        assert not grounded
        assert "no evidence" in detail

    def test_very_short_quote_is_rejected(self) -> None:
        """A two-word fragment would match almost any document."""
        grounded, detail = check_evidence_grounded("76 cases", self.SOURCE)
        assert not grounded
        assert "too short" in detail


class TestLabelProximity:
    """The check that catches real misassignment, where numbers and quotes
    are both genuine but the field is wrong."""

    def test_correct_assignment_passes(self) -> None:
        passed, _, _ = check_label_proximity(
            76, "cases_confirmed", "Tshopo has recorded 76 cases and 27 deaths."
        )
        assert passed

    def test_deaths_beside_death_wording_passes(self) -> None:
        passed, _, _ = check_label_proximity(
            27, "deaths", "Tshopo has recorded 76 cases and 27 deaths."
        )
        assert passed

    def test_recoveries_read_as_suspected_cases_is_rejected(self) -> None:
        """Observed in the saved Agent response: "2595 recoveries"."""
        passed, detail, _ = check_label_proximity(
            2595,
            "cases_suspected",
            "cumulative confirmed cases have reached 9704, including 4687 deaths "
            "and 2595 recoveries.",
        )
        assert not passed
        assert "recover" in detail

    def test_swapped_cases_and_deaths_are_both_rejected(self) -> None:
        """Observed in the saved Agent response."""
        evidence = (
            "An additional 976 confirmed cases, including 482 confirmed deaths, have been reported."
        )
        assert not check_label_proximity(976, "deaths", evidence)[0]
        assert not check_label_proximity(482, "cases_suspected", evidence)[0]
        # The correct assignments still pass, so the check is not simply strict.
        assert check_label_proximity(976, "cases_confirmed", evidence)[0]
        assert check_label_proximity(482, "deaths", evidence)[0]

    def test_a_coverage_ratio_is_not_a_case_count(self) -> None:
        """Observed in the saved Agent response: "Haut-Uele (89.9%; 1286/1430)"."""
        passed, _, _ = check_label_proximity(
            1286,
            "cases_confirmed",
            "Four provinces were below the threshold: Haut-Uele (89.9%; 1286/1430)",
        )
        assert not passed

    def test_a_label_beyond_the_window_does_not_count(self) -> None:
        far = "x" * (LABEL_WINDOW + 30)
        passed, _, _ = check_label_proximity(500, "deaths", f"The figure 500 {far} deaths")
        assert not passed

    def test_a_number_absent_from_the_evidence_is_rejected(self) -> None:
        passed, detail, _ = check_label_proximity(999, "deaths", "There were 27 deaths.")
        assert not passed
        assert "not present" in detail

    def test_an_unknown_field_is_not_rejected_by_this_check(self) -> None:
        """Absence of a vocabulary must not silently reject a field."""
        passed, detail, _ = check_label_proximity(5, "hospitalisations", "5 hospitalisations")
        assert passed
        assert "no label vocabulary" in detail


class TestGroundRecord:
    SOURCE = (
        "Ituri remains the epicentre, with 7040 cumulative confirmed cases and "
        "3271 deaths. Nord Kivu follows with 2146 confirmed cases."
    )

    def test_fabricated_value_is_rejected_as_not_in_source(self) -> None:
        report = ground_record(
            {"cases_confirmed": 7040, "cases_suspected": 9291},
            evidence="Ituri remains the epicentre, with 7040 cumulative confirmed cases and 3271 deaths.",
            source_text=self.SOURCE,
        )
        assert report.usable_fields == {"cases_confirmed": 7040}
        assert report.rejected_fields[0].verdict is Verdict.NOT_IN_SOURCE

    def test_value_from_another_sentence_is_rejected(self) -> None:
        report = ground_record(
            {"cases_confirmed": 2146},
            evidence="Ituri remains the epicentre, with 7040 cumulative confirmed cases and 3271 deaths.",
            source_text=self.SOURCE,
        )
        assert not report.any_grounded
        assert report.rejected_fields[0].verdict is Verdict.NOT_IN_EVIDENCE

    def test_none_values_are_skipped_not_grounded(self) -> None:
        """ "Not stated" needs no grounding and must not become a rejection."""
        report = ground_record(
            {"cases_confirmed": 7040, "deaths": None, "cases_suspected": None},
            evidence="Ituri remains the epicentre, with 7040 cumulative confirmed cases and 3271 deaths.",
            source_text=self.SOURCE,
        )
        assert len(report.fields) == 1
        assert report.all_grounded

    def test_ungrounded_evidence_demotes_every_field(self) -> None:
        """If the quote cannot be verified, nothing ties a number to this row."""
        report = ground_record(
            {"cases_confirmed": 7040, "deaths": 3271},
            evidence="A sentence that is nowhere in the document whatsoever.",
            source_text=self.SOURCE,
        )
        assert not report.any_grounded
        assert all(v.verdict is Verdict.GROUNDED_WEAK for v in report.fields)

    def test_missing_evidence_is_distinguished_from_wrong_evidence(self) -> None:
        report = ground_record({"cases_confirmed": 7040}, evidence=None, source_text=self.SOURCE)
        assert report.fields[0].verdict is Verdict.NO_EVIDENCE_PROVIDED

    def test_weak_grounding_is_not_usable(self) -> None:
        """A number present in the document is not enough on its own."""
        assert Verdict.GROUNDED_WEAK.is_usable is False
        assert Verdict.GROUNDED.is_usable is True

    def test_report_serialises_for_the_jsonb_column(self) -> None:
        report = ground_record(
            {"cases_confirmed": 7040, "cases_suspected": 9291},
            evidence="Ituri remains the epicentre, with 7040 cumulative confirmed cases and 3271 deaths.",
            source_text=self.SOURCE,
        )
        detail = report.to_detail()
        assert detail["evidence_grounded"] is True
        fields = detail["fields"]
        assert isinstance(fields, list)
        assert {f["field"] for f in fields} == {"cases_confirmed", "cases_suspected"}
        assert all("verdict" in f and "detail" in f for f in fields)

    def test_empty_record_is_trivially_grounded(self) -> None:
        report = ground_record({}, evidence=self.SOURCE, source_text=self.SOURCE)
        assert report.all_grounded
        assert not report.any_grounded


class TestAgainstRealAgentResponse:
    """Run the gate over a genuine TinyFish Agent response.

    The expected outcome was verified by reading the source text by hand. These
    assertions are the project's guarantee that structured extraction alone is
    not trusted.
    """

    FIELDS = ("cases_confirmed", "cases_probable", "cases_suspected", "deaths")

    # (row index, field) -> value. Each was checked against the quoted sentence
    # in the source document.
    EXPECTED_ACCEPTED: frozenset[tuple[int, str, int]] = frozenset(
        {
            (0, "cases_confirmed", 7040),
            (0, "deaths", 3271),
            (1, "cases_confirmed", 2146),
            (1, "deaths", 1199),
            (2, "cases_confirmed", 421),
            (2, "deaths", 183),
            (3, "cases_confirmed", 76),
            (3, "deaths", 27),
            (4, "cases_confirmed", 9704),
            (4, "deaths", 4687),
            (5, "cases_confirmed", 976),
            (6, "cases_confirmed", 37),
        }
    )

    @pytest.fixture
    def agent_case(self, load_json_fixture: Any) -> tuple[str, list[dict[str, Any]]]:
        fetch = load_json_fixture("tinyfish/fetch_don622_response.json")
        agent = load_json_fixture("tinyfish/agent_run_don622_completed.json")
        return fetch["results"][0]["text"], agent["result"]["locations"]

    def test_exactly_the_hand_verified_values_are_accepted(
        self, agent_case: tuple[str, list[dict[str, Any]]]
    ) -> None:
        source, locations = agent_case
        accepted: set[tuple[int, str, int]] = set()
        for index, location in enumerate(locations):
            report = ground_record(
                {name: location.get(name) for name in self.FIELDS},
                evidence=location.get("evidence"),
                source_text=source,
            )
            for name, value in report.usable_fields.items():
                accepted.add((index, name, value))

        assert accepted == set(self.EXPECTED_ACCEPTED), (
            "the gate's verdicts changed; re-verify against the source text before "
            "updating this expectation"
        )

    @pytest.mark.parametrize(
        ("row", "field", "value", "expected_verdict"),
        [
            # Numbers that appear nowhere in the source document.
            (0, "cases_suspected", 9291, Verdict.NOT_IN_SOURCE),
            (2, "cases_suspected", 123, Verdict.NOT_IN_SOURCE),
            (7, "cases_suspected", 423, Verdict.NOT_IN_SOURCE),
            # Numbers in the document but not in the sentence the row cites.
            (3, "cases_suspected", 3, Verdict.NOT_IN_EVIDENCE),
            (6, "deaths", 4687, Verdict.NOT_IN_EVIDENCE),
            (7, "deaths", 183, Verdict.NOT_IN_EVIDENCE),
            # Numbers whose surrounding wording describes something else.
            (4, "cases_suspected", 2595, Verdict.LABEL_MISMATCH),  # "recoveries"
            (5, "deaths", 976, Verdict.LABEL_MISMATCH),  # swapped
            (5, "cases_suspected", 482, Verdict.LABEL_MISMATCH),  # swapped
            (7, "cases_confirmed", 1286, Verdict.LABEL_MISMATCH),  # coverage ratio
        ],
    )
    def test_each_known_error_gets_its_specific_verdict(
        self,
        agent_case: tuple[str, list[dict[str, Any]]],
        row: int,
        field: str,
        value: int,
        expected_verdict: Verdict,
    ) -> None:
        source, locations = agent_case
        location = locations[row]
        assert location.get(field) == value, "fixture changed; re-verify the error table"
        report = ground_record(
            {name: location.get(name) for name in self.FIELDS},
            evidence=location.get("evidence"),
            source_text=source,
        )
        verdict = next(v for v in report.fields if v.field_name == field)
        assert verdict.verdict is expected_verdict
        assert not verdict.is_usable

    def test_half_the_extracted_fields_are_rejected(
        self, agent_case: tuple[str, list[dict[str, Any]]]
    ) -> None:
        """Documents the scale of the problem the gate exists to solve."""
        source, locations = agent_case
        usable = rejected = 0
        for location in locations:
            report = ground_record(
                {name: location.get(name) for name in self.FIELDS},
                evidence=location.get("evidence"),
                source_text=source,
            )
            usable += len(report.usable_fields)
            rejected += len(report.rejected_fields)
        assert usable == 12
        assert rejected == 12
