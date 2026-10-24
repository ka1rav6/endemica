from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from epiroute.core.config import Settings
from epiroute.ingestion.html_text import html_to_text, join_sections, normalise_whitespace
from epiroute.ingestion.who_don import disease_label_from_title, parse_don_item

NOW = datetime(2026, 10, 24, tzinfo=UTC)


@pytest.fixture
def settings() -> Settings:
    return Settings()


class TestHtmlToText:
    def test_tags_are_stripped(self) -> None:
        assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_entities_are_decoded(self) -> None:
        assert html_to_text("<p>5&nbsp;cases &amp; 2 deaths</p>").replace(" ", " ") == (
            "5 cases & 2 deaths"
        )

    def test_scripts_and_styles_are_removed(self) -> None:
        text = html_to_text("<p>keep</p><script>drop()</script><style>.x{}</style>")
        assert "drop" not in text
        assert "keep" in text

    def test_block_tags_become_line_breaks(self) -> None:
        text = html_to_text("<p>one</p><p>two</p>")
        assert "one" in text and "two" in text
        assert text.count("\n") >= 1

    def test_table_cells_are_preserved(self) -> None:
        text = html_to_text("<table><tr><td>Ituri</td><td>7040</td></tr></table>")
        assert "Ituri" in text
        assert "7040" in text

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_input_gives_empty_text(self, value: str | None) -> None:
        assert html_to_text(value) == ""

    def test_whitespace_is_normalised(self) -> None:
        assert normalise_whitespace("a   b\n\n\n\nc") == "a b\n\nc"

    def test_join_sections_skips_empty_sections(self) -> None:
        joined = join_sections("<p>first</p>", None, "", "<p>second</p>")
        assert "first" in joined and "second" in joined


class TestDiseaseLabel:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Ebola disease – Uganda", "Ebola disease"),
            (
                "Middle East respiratory syndrome coronavirus - Saudi Arabia",
                "Middle East respiratory syndrome coronavirus",
            ),
            ("Cholera, Global situation", "Cholera"),
            ("Mpox", "Mpox"),
        ],
    )
    def test_label_is_the_part_before_the_place(self, title: str, expected: str) -> None:
        assert disease_label_from_title(title) == expected

    def test_empty_title_gives_none(self) -> None:
        assert disease_label_from_title("") is None


class TestParseDonItem:
    def _item(self, **overrides: Any) -> dict[str, Any]:
        item: dict[str, Any] = {
            "DonId": "2026-DON999",
            "UrlName": "2026-DON999",
            "Title": "Ebola disease – Democratic Republic of the Congo",
            "PublicationDateAndTime": "2026-10-20T15:00:00Z",
            "PublicationDate": "2026-10-20T00:00:00Z",
            "Summary": "<p>Summary text.</p>",
            "Overview": "<p>There were 10 confirmed cases and 2 deaths.</p>",
            "Epidemiology": None,
            "Assessment": "<p>Risk assessed as high.</p>",
        }
        item.update(overrides)
        return item

    def test_full_item_parses(self, settings: Settings) -> None:
        record = parse_don_item(self._item(), settings=settings, retrieved_at=NOW)
        assert record is not None
        assert record.source_identifier == "2026-DON999"
        assert record.published_at == datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
        assert record.disease_label == "Ebola disease"
        assert record.pathogen_key == "low_mobility_severe"
        assert "10 confirmed cases" in record.narrative_text
        assert record.source_url.endswith("/2026-DON999")
        assert len(record.content_sha256) == 64

    def test_empty_epidemiology_field_does_not_lose_the_overview(self, settings: Settings) -> None:
        record = parse_don_item(self._item(Epidemiology=""), settings=settings, retrieved_at=NOW)
        assert record is not None
        assert "10 confirmed cases" in record.narrative_text

    def test_missing_identifier_is_rejected(self, settings: Settings) -> None:
        item = self._item(DonId="", UrlName="", Id=None)
        assert parse_don_item(item, settings=settings, retrieved_at=NOW) is None

    def test_url_name_is_used_when_don_id_is_blank(self, settings: Settings) -> None:
        record = parse_don_item(self._item(DonId=""), settings=settings, retrieved_at=NOW)
        assert record is not None
        assert record.source_identifier == "2026-DON999"

    def test_missing_title_is_rejected(self, settings: Settings) -> None:
        assert parse_don_item(self._item(Title=""), settings=settings, retrieved_at=NOW) is None

    def test_unparseable_date_becomes_none_not_an_error(self, settings: Settings) -> None:
        record = parse_don_item(
            self._item(PublicationDateAndTime="not a date", PublicationDate="also not"),
            settings=settings,
            retrieved_at=NOW,
        )
        assert record is not None
        assert record.published_at is None

    def test_falls_back_to_publication_date(self, settings: Settings) -> None:
        record = parse_don_item(
            self._item(PublicationDateAndTime=None), settings=settings, retrieved_at=NOW
        )
        assert record is not None
        assert record.published_at == datetime(2026, 10, 20, tzinfo=UTC)

    def test_unmatched_disease_gets_no_profile(self, settings: Settings) -> None:
        record = parse_don_item(
            self._item(Title="Nipah virus infection – Bangladesh"),
            settings=settings,
            retrieved_at=NOW,
        )
        assert record is not None
        assert record.pathogen_key is None

    def test_identical_content_hashes_identically(self, settings: Settings) -> None:
        a = parse_don_item(self._item(), settings=settings, retrieved_at=NOW)
        b = parse_don_item(self._item(), settings=settings, retrieved_at=NOW)
        assert a is not None and b is not None
        assert a.content_sha256 == b.content_sha256

    def test_changed_content_changes_the_hash(self, settings: Settings) -> None:
        a = parse_don_item(self._item(), settings=settings, retrieved_at=NOW)
        b = parse_don_item(
            self._item(Overview="<p>There were 11 confirmed cases.</p>"),
            settings=settings,
            retrieved_at=NOW,
        )
        assert a is not None and b is not None
        assert a.content_sha256 != b.content_sha256


class TestAgainstRealApiFixture:
    def test_live_api_shape_parses(self, load_json_fixture: Any, settings: Settings) -> None:
        payload = load_json_fixture("who_don/don_listing_top5.json")
        records = [
            parse_don_item(item, settings=settings, retrieved_at=NOW) for item in payload["value"]
        ]
        parsed = [r for r in records if r is not None]
        assert len(parsed) == 5
        assert all(r.narrative_text for r in parsed)
        assert all(r.published_at is not None for r in parsed)
        assert all(r.source_url.startswith("https://www.who.int/") for r in parsed)

    def test_overview_carries_the_narrative(self, load_json_fixture: Any) -> None:
        payload = load_json_fixture("who_don/don_listing_top5.json")
        assert all((item.get("Overview") or "").strip() for item in payload["value"])

    def test_narrative_does_not_depend_on_the_epidemiology_field(
        self, load_json_fixture: Any, settings: Settings
    ) -> None:
        payload = load_json_fixture("who_don/don_listing_top5.json")
        without_epidemiology = [{**item, "Epidemiology": None} for item in payload["value"]]
        records = [
            parse_don_item(item, settings=settings, retrieved_at=NOW)
            for item in without_epidemiology
        ]
        assert all(r is not None and len(r.narrative_text) > 500 for r in records)
