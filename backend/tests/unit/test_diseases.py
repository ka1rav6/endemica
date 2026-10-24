from __future__ import annotations

import pytest

from epiroute.epidemiology.diseases import OTHER_KEY, classify, extract_label, resolve


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
