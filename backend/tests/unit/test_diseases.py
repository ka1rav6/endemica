from __future__ import annotations

from datetime import UTC, datetime

import pytest

from endemica.epidemiology.diseases import OTHER_KEY, classify, extract_label, resolve


class TestLabelExtraction:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            # The 2026-era format: disease, then an en dash, then the country.
            ("Cholera – Nigeria", "Cholera"),
            ("Ebola virus disease – Democratic Republic of the Congo", "Ebola virus disease"),
            ("Mpox", "Mpox"),
            # The 1996-2003 format carries a year prefix and an update suffix.
            ("1998 - Cholera in Uganda", "Cholera"),
            ("2001- Cholera in South Africa - Update 12", "Cholera"),
            ("1999 - Yellow fever in Bolivia - Update", "Yellow fever"),
            (
                "2002 - Acute watery diarrhoeal syndrome in Afghanistan",
                "Acute watery diarrhoeal syndrome",
            ),
            # A comma that introduces a place is dropped; one inside a name is not.
            ("Cholera, Global situation", "Cholera"),
            ("Hand, foot and mouth disease – Viet Nam", "Hand, foot and mouth disease"),
        ],
    )
    def test_strips_year_country_and_update(self, title: str, expected: str) -> None:
        assert extract_label(title) == expected

    def test_empty_title_has_no_label(self) -> None:
        assert extract_label("") is None
        assert extract_label("   ") is None


class TestCanonicalGrouping:
    @pytest.mark.parametrize(
        ("title", "expected_key"),
        [
            ("Yellow fever – Ghana", "yellow_fever"),
            ("Yellow Fever - Ghana", "yellow_fever"),
            ("1999 - Yellow fever in Bolivia - Update", "yellow_fever"),
            ("Middle East respiratory syndrome coronavirus (MERS-CoV) – Saudi Arabia", "mers"),
            ("Middle East respiratory syndrome coronavirus – Oman", "mers"),
            ("Ebola virus disease, West Africa", "ebola"),
            ("Ebola disease caused by Sudan ebolavirus – Uganda", "ebola"),
            ("Sudan virus disease – Uganda", "ebola"),
            ("Pandemic (H1N1) 2009", "influenza_h1n1"),
            ("Human infection with avian influenza A(H7N9) virus – China", "influenza_h7n9"),
            ("Avian influenza – situation in Egypt – update 10", "influenza_h5n1"),
        ],
    )
    def test_wording_variants_group_onto_one_key(self, title: str, expected_key: str) -> None:
        key, _, _, _ = resolve(title)
        assert key == expected_key

    def test_sars_does_not_absorb_sars_cov_2(self) -> None:
        assert resolve("Severe Acute Respiratory Syndrome (SARS)")[0] == "sars"
        assert resolve("Novel coronavirus infection – China")[0] == "covid19"

    def test_h7n9_is_not_folded_into_the_h5n1_bucket(self) -> None:
        assert resolve("Avian influenza A(H7N9) virus – China")[0] == "influenza_h7n9"
        assert resolve("Avian influenza A(H5N1) – Cambodia")[0] == "influenza_h5n1"

    def test_a_name_with_no_pattern_falls_into_the_other_bucket(self) -> None:
        key, name, family, label = resolve("1997 - International Travel and Health")
        assert key == OTHER_KEY
        assert name and family
        # The source's own wording is still kept, so nothing is lost.
        assert label == "International Travel and Health"

    def test_classify_reads_every_candidate(self) -> None:
        # The label alone says nothing; the full title names the pathogen.
        assert classify(None, "Human infection with avian influenza A(H9N2) – China") is not None

    def test_resolve_prefers_an_explicit_label(self) -> None:
        _, _, _, label = resolve("Cholera – Nigeria", label="Vibrio cholerae O1")
        assert label == "Vibrio cholerae O1"


class TestNamesTheSourceReused:
    """WHO called MERS "novel coronavirus infection" until May 2013."""

    @pytest.mark.parametrize(
        "published",
        [datetime(2012, 9, 23, tzinfo=UTC), datetime(2013, 5, 23, tzinfo=UTC)],
    )
    def test_novel_coronavirus_before_2019_is_mers(self, published: datetime) -> None:
        key, name, _, _ = resolve("Novel coronavirus infection - update", published_at=published)
        assert key == "mers"
        assert name == "MERS-CoV"

    @pytest.mark.parametrize(
        "published",
        [datetime(2020, 1, 12, tzinfo=UTC), datetime(2021, 6, 1, tzinfo=UTC)],
    )
    def test_novel_coronavirus_from_2020_is_covid(self, published: datetime) -> None:
        assert resolve("Novel Coronavirus - China", published_at=published)[0] == "covid19"

    def test_an_explicit_covid_name_is_never_rerouted(self) -> None:
        # A back-dated or undated report that names SARS-CoV-2 outright stays COVID-19.
        early = datetime(2013, 1, 1, tzinfo=UTC)
        assert resolve("SARS-CoV-2 Variant - United Kingdom", published_at=early)[0] == "covid19"
        assert resolve("COVID-19 - Global Situation", published_at=early)[0] == "covid19"

    def test_without_a_date_the_modern_reading_is_kept(self) -> None:
        assert resolve("Novel coronavirus infection - update")[0] == "covid19"

    def test_other_diseases_are_untouched_by_the_date(self) -> None:
        old = datetime(2001, 1, 1, tzinfo=UTC)
        assert resolve("Cholera in Uganda", published_at=old)[0] == "cholera"
