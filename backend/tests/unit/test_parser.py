from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from endemica.ingestion.grounding import ground_record
from endemica.ingestion.parser import (
    find_country_in_sentence,
    find_outbreak_start,
    parse_report,
    parse_sentence,
    split_sentences,
)


class TestSentenceSplitting:
    def test_splits_on_sentence_boundaries(self) -> None:
        assert len(split_sentences("One thing. Two things. Three things.")) == 3

    def test_collapses_whitespace(self) -> None:
        assert split_sentences("A  b\n\nc.") == ["A b c."]

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_empty_text_gives_no_sentences(self, text: str) -> None:
        assert split_sentences(text) == []


class TestFieldExtraction:
    @pytest.mark.parametrize(
        ("sentence", "field", "value"),
        [
            ("There were 42 confirmed cases.", "cases_confirmed", 42),
            ("There were 42 laboratory-confirmed cases.", "cases_confirmed", 42),
            ("A total of 1,234 confirmed cases was reported.", "cases_confirmed", 1234),
            ("Some 17 probable cases occurred.", "cases_probable", 17),
            ("There were 9 suspected cases.", "cases_suspected", 9),
            ("There were 9 suspect cases.", "cases_suspected", 9),
            ("Reports describe 5 deaths.", "deaths", 5),
            ("Reports describe 5 associated deaths.", "deaths", 5),
            ("A cumulative total of 300 confirmed cases.", "cases_confirmed", 300),
            (
                "Cumulative confirmed cases have reached 9704, including 4687 deaths.",
                "cases_confirmed",
                9704,
            ),
        ],
    )
    def test_patterns_match(self, sentence: str, field: str, value: int) -> None:
        parsed = parse_sentence(sentence)
        assert parsed is not None
        assert parsed.values[field] == value

    def test_multiple_fields_in_one_sentence(self) -> None:
        parsed = parse_sentence("Tshopo recorded 76 confirmed cases and 27 deaths.")
        assert parsed is not None
        assert parsed.values == {"cases_confirmed": 76, "deaths": 27}

    @pytest.mark.parametrize(
        "sentence",
        [
            "Vaccination coverage reached 89 per cent of the target.",
            "2595 recoveries were recorded.",
            "A total of 5500 laboratory tests were conducted.",
            "412 contacts were traced.",
            "Some 30 beds were added.",
            "1200 doses were administered.",
        ],
    )
    def test_non_case_sentences_are_excluded(self, sentence: str) -> None:
        assert parse_sentence(sentence) is None

    def test_sentence_without_numbers_yields_nothing(self) -> None:
        assert parse_sentence("The outbreak continues to expand.") is None

    def test_a_recovery_count_does_not_hide_the_cumulative_total(self) -> None:
        """WHO puts the national total and the recovery count in one sentence."""
        parsed = parse_sentence(
            "As of 20 October, cumulative confirmed cases have reached 9704, "
            "including 4687 deaths and 2595 recoveries."
        )
        assert parsed is not None
        assert parsed.values == {"cases_confirmed": 9704, "deaths": 4687}
        values: dict[str, int | None] = dict(parsed.values)
        grounded = ground_record(values, evidence=parsed.sentence, source_text=parsed.sentence)
        assert grounded.usable_fields == {"cases_confirmed": 9704, "deaths": 4687}

    def test_declaration_date_is_the_outbreak_start(self) -> None:
        text = (
            "The patient died on 5 October 2026. Cases have been reported since "
            "the declaration of the outbreak on 15 May 2026."
        )
        assert find_outbreak_start(text) == date(2026, 5, 15)

    def test_a_death_date_alone_is_not_an_outbreak_start(self) -> None:
        assert find_outbreak_start("The patient died on 5 October 2026.") is None


class TestCountryAttribution:
    @pytest.mark.parametrize(
        ("sentence", "fallback", "expected"),
        [
            ("Overall, 3269 deaths have been reported, including two in Uganda.", "COD", "COD"),
            ("Nord Kivu follows with 2146 confirmed cases.", "COD", "COD"),
            ("Kenya has reported 3 confirmed cases.", "COD", "KEN"),
            ("Saudi Arabia reported 8 laboratory-confirmed cases.", "SAU", "SAU"),
            ("A total of 12 confirmed cases occurred.", None, None),
        ],
    )
    def test_attribution(self, sentence: str, fallback: str | None, expected: str | None) -> None:
        parsed = parse_sentence(sentence)
        anchor = min(parsed.positions.values()) if parsed and parsed.positions else None
        assert find_country_in_sentence(sentence, fallback, number_position=anchor) == expected

    def test_subset_mention_does_not_capture_the_headline_number(self) -> None:
        """ "including two in Uganda" must not reassign a global total."""
        sentence = "Overall, 3269 deaths have been reported, including two in Uganda."
        assert find_country_in_sentence(sentence, "COD", number_position=9) == "COD"

    def test_distant_country_mention_is_ignored(self) -> None:
        sentence = "A total of 500 confirmed cases " + "x" * 80 + " in Uganda."
        assert find_country_in_sentence(sentence, "COD", number_position=11) == "COD"

    def test_report_country_wins_when_both_are_named(self) -> None:
        sentence = "Kenya and the Democratic Republic of the Congo reported 5 confirmed cases."
        assert find_country_in_sentence(sentence, "COD", number_position=55) == "COD"


class TestParseReport:
    def test_title_country_is_the_fallback(self) -> None:
        report = parse_report(
            "A cumulative total of 40 confirmed cases has been reported.",
            title="Ebola disease – Democratic Republic of the Congo",
        )
        assert [loc.country for loc in report.locations] == ["COD"]

    def test_every_location_carries_its_evidence(self) -> None:
        text = "Ituri recorded 70 confirmed cases. Tshopo recorded 5 deaths."
        report = parse_report(text, title="Ebola – Democratic Republic of the Congo")
        assert all(loc.evidence for loc in report.locations)

    def test_no_numbers_gives_no_locations(self) -> None:
        report = parse_report("The outbreak continues.", title="Ebola – Uganda")
        assert report.locations == []

    def test_disease_label_is_carried_through(self) -> None:
        report = parse_report("5 confirmed cases.", title="X – Uganda", disease_label="Mpox")
        assert report.disease == "Mpox"


class TestParserOutputIsFullyGroundable:
    """Everything the parser emits must survive the gate it is checked against."""

    def test_real_who_page_yields_only_grounded_values(self, load_json_fixture: Any) -> None:
        text = load_json_fixture("tinyfish/fetch_don622_response.json")["results"][0]["text"]
        report = parse_report(
            text,
            title=(
                "Ebola disease caused by Bundibugyo virus, Democratic Republic of the Congo, "
                "Kenya and Nigeria"
            ),
            disease_label="Ebola disease caused by Bundibugyo virus",
        )
        assert report.locations
        usable = rejected = 0
        for location in report.locations:
            outcome = ground_record(
                location.numeric_fields(), evidence=location.evidence, source_text=text
            )
            usable += len(outcome.usable_fields)
            rejected += len(outcome.rejected_fields)
        assert rejected == 0
        assert usable >= 8

    def test_all_values_are_attributed_to_the_reporting_country(
        self, load_json_fixture: Any
    ) -> None:
        text = load_json_fixture("tinyfish/fetch_don622_response.json")["results"][0]["text"]
        report = parse_report(
            text,
            title=(
                "Ebola disease caused by Bundibugyo virus, Democratic Republic of the Congo, "
                "Kenya and Nigeria"
            ),
        )
        assert {loc.country for loc in report.locations} == {"COD"}
