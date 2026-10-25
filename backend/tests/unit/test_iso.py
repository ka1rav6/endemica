from __future__ import annotations

import pytest

from endemica.core.errors import DataValidationError
from endemica.datasets.iso import (
    country_name,
    is_known_iso3,
    resolve,
    resolve_strict,
)


class TestResolvesWhatPycountryCannot:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Turkey", "TUR"),
            ("Türkiye", "TUR"),
            ("Russia", "RUS"),
            ("UK", "GBR"),
            ("Cape Verde", "CPV"),
            ("Swaziland", "SWZ"),
            ("Burma", "MMR"),
            ("Macedonia", "MKD"),
            ("Palestine", "PSE"),
            ("Macau", "MAC"),
            ("Ivory Coast", "CIV"),
            ("Cote d'Ivoire", "CIV"),
            ("Kosovo", "XKX"),
            ("EL", "GRC"),
            ("XK", "XKX"),
            ("East Timor", "TLS"),
            ("The Gambia", "GMB"),
            ("Czech Republic", "CZE"),
        ],
    )
    def test_common_variants_resolve(self, name: str, expected: str) -> None:
        assert resolve(name) == expected


class TestCongoDisambiguation:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Democratic Republic of the Congo", "COD"),
            ("DR Congo", "COD"),
            ("DRC", "COD"),
            ("Congo (Kinshasa)", "COD"),
            ("Zaire", "COD"),
            ("Congo", "COG"),
            ("Republic of the Congo", "COG"),
            ("Congo (Brazzaville)", "COG"),
        ],
    )
    def test_the_two_congos_never_collide(self, name: str, expected: str) -> None:
        assert resolve(name) == expected


class TestParentheticalQualifiers:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Bolivia (Plurinational State of)", "BOL"),
            ("Iran (Islamic Republic of)", "IRN"),
            ("Micronesia (Federated States of)", "FSM"),
            ("Virgin Islands (U.S.)", "VIR"),
            ("Korea, Republic of", "KOR"),
            ("Tanzania, United Republic of", "TZA"),
        ],
    )
    def test_qualifiers_are_handled(self, name: str, expected: str) -> None:
        assert resolve(name) == expected


class TestAggregatesAreRejected:
    @pytest.mark.parametrize(
        "name",
        [
            "World",
            "Global",
            "Global situation",
            "Europe",
            "Africa",
            "Asia",
            "European Union",
            "Multiple countries",
            "Unknown",
            "Not specified",
            "European Region",
            "African Region",
        ],
    )
    def test_aggregates_resolve_to_none(self, name: str) -> None:
        assert resolve(name) is None


class TestCodes:
    @pytest.mark.parametrize("code", ["DE", "de", "DEU", "deu"])
    def test_codes_resolve_to_alpha3(self, code: str) -> None:
        assert resolve(code) == "DEU"

    @pytest.mark.parametrize("code", ["-99", "", "ZZ", "ZZZ"])
    def test_placeholder_codes_resolve_to_none(self, code: str) -> None:
        assert resolve(code) is None

    def test_extra_codes_are_accepted(self) -> None:
        assert resolve("XKX") == "XKX"
        assert is_known_iso3("XKX")


class TestNoFuzzyMatching:
    @pytest.mark.parametrize("name", ["Guinea-Bissau", "Papua New Guinea", "Equatorial Guinea"])
    def test_similar_names_do_not_collapse_to_guinea(self, name: str) -> None:
        assert resolve(name) != resolve("Guinea")

    @pytest.mark.parametrize("name", ["Atlantis", "Westeros", "Freedonia", "qqqqq"])
    def test_unknown_names_resolve_to_none(self, name: str) -> None:
        assert resolve(name) is None

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_empty_input_resolves_to_none(self, name: str | None) -> None:
        assert resolve(name) is None


class TestStrictResolution:
    def test_known_name_returns_code(self) -> None:
        assert resolve_strict("Germany") == "DEU"

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(DataValidationError, match="could not resolve"):
            resolve_strict("Atlantis")

    def test_error_includes_context(self) -> None:
        with pytest.raises(DataValidationError, match=r"example\.invalid"):
            resolve_strict("Atlantis", context="https://example.invalid/report")

    def test_aggregate_raises_rather_than_mapping(self) -> None:
        with pytest.raises(DataValidationError):
            resolve_strict("Global situation")


class TestDisplayNames:
    def test_known_code_gets_a_name(self) -> None:
        assert country_name("DEU") == "Germany"

    def test_extra_code_gets_a_name(self) -> None:
        assert country_name("XKX") == "Kosovo"

    def test_unknown_code_falls_back_to_the_code(self) -> None:
        assert country_name("QQQ") == "QQQ"
