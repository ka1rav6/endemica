"""Pathogen profile registry: integrity, matching and honesty guarantees."""

from __future__ import annotations

import pytest

from endemica.core.errors import ModelInputError
from endemica.epidemiology.establishment import solve_establishment
from endemica.epidemiology.profiles import (
    DEFAULT_PROFILE_KEY,
    PROFILES,
    Confidence,
    ParameterBasis,
    ParameterRange,
    get_profile,
    match_profile_key,
)


class TestRegistryIntegrity:
    def test_default_profile_exists(self) -> None:
        assert DEFAULT_PROFILE_KEY in PROFILES

    def test_every_profile_key_matches_its_registry_entry(self) -> None:
        for key, profile in PROFILES.items():
            assert profile.key == key

    def test_every_profile_cites_at_least_one_reference(self) -> None:
        for profile in PROFILES.values():
            assert profile.references, f"{profile.key} has no references"

    def test_every_parameter_range_is_ordered(self) -> None:
        for profile in PROFILES.values():
            for name in ("alpha", "reproduction_number", "dispersion_k"):
                r: ParameterRange = getattr(profile, name)
                assert r.low <= r.central <= r.high, f"{profile.key}.{name}"

    def test_alpha_stays_a_probability(self) -> None:
        for profile in PROFILES.values():
            assert 0.0 <= profile.alpha.low <= profile.alpha.high <= 1.0, profile.key

    def test_dispersion_is_positive_where_establishment_is_estimable(self) -> None:
        for profile in PROFILES.values():
            if profile.establishment_estimable:
                assert profile.dispersion_k.low > 0, profile.key

    def test_periods_are_positive(self) -> None:
        for profile in PROFILES.values():
            assert profile.infectious_period_days > 0, profile.key
            assert profile.incubation_period_days > 0, profile.key

    def test_registry_is_read_only(self) -> None:
        """A mutable registry would let one request change another's parameters."""
        with pytest.raises(TypeError):
            PROFILES["respiratory_default"] = PROFILES["vector_borne"]  # type: ignore[index]


class TestHonestyGuarantees:
    def test_uncited_parameters_are_labelled_as_project_assumptions(self) -> None:
        """Every alpha is Endemica's assumption; none may claim a citation."""
        for profile in PROFILES.values():
            assert profile.alpha.basis is ParameterBasis.PROJECT_ASSUMPTION, profile.key
            assert profile.alpha.note, f"{profile.key} alpha has no explanation"

    def test_non_estimable_profiles_explain_themselves(self) -> None:
        for profile in PROFILES.values():
            if not profile.establishment_estimable:
                assert profile.establishment_note
                assert profile.confidence is Confidence.INDICATIVE_ONLY

    def test_unused_r_values_are_subcritical_so_accidental_use_yields_zero(self) -> None:
        """Defence in depth: if a non-estimable profile's R leaked into the
        model, it must produce 0, not a misleading positive probability."""
        for profile in PROFILES.values():
            if not profile.establishment_estimable:
                result = solve_establishment(
                    profile.reproduction_number.high, profile.dispersion_k.central
                )
                assert result.establishment_probability == 0.0, profile.key

    def test_alpha_ordering_matches_the_research_note(self) -> None:
        """The note ranks boarding-while-infectious: Zika high, Ebola very low."""
        vector = PROFILES["vector_borne"].alpha.central
        respiratory = PROFILES["respiratory_default"].alpha.central
        hospital = PROFILES["hospital_amplified"].alpha.central
        ebola = PROFILES["low_mobility_severe"].alpha.central
        assert vector > respiratory > hospital > ebola

    def test_mers_profile_stays_subcritical_in_the_community(self) -> None:
        """The note's negative control: airline volume must not make MERS a pandemic."""
        profile = PROFILES["hospital_amplified"]
        assert profile.reproduction_number.high < 1.0
        assert (
            solve_establishment(
                profile.reproduction_number.high, profile.dispersion_k.central
            ).establishment_probability
            == 0.0
        )


class TestProfileLookup:
    def test_known_key_is_returned(self) -> None:
        assert get_profile("respiratory_default").key == "respiratory_default"

    def test_unknown_key_raises_rather_than_defaulting(self) -> None:
        """Silently defaulting would change every published number."""
        with pytest.raises(ModelInputError, match="unknown pathogen profile"):
            get_profile("made_up")


class TestAliasMatching:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Ebola disease caused by Bundibugyo virus", "low_mobility_severe"),
            ("Marburg virus disease - Rwanda", "low_mobility_severe"),
            ("Middle East respiratory syndrome coronavirus", "hospital_amplified"),
            ("MERS-CoV - Saudi Arabia", "hospital_amplified"),
            ("Zika virus disease - India", "vector_borne"),
            ("Dengue - Global situation", "vector_borne"),
            ("Cholera - Global situation", "enteric_waterborne"),
            ("Avian Influenza A(H5N1) - Cambodia", "avian_influenza"),
            ("Influenza A(H5N1) - Cambodia", "avian_influenza"),
            ("Human infection with influenza A(H5N1) virus", "avian_influenza"),
            ("COVID-19", "covid_19"),
            ("Pneumonia of undetermined etiology", "covid_19"),
            ("Seasonal influenza - Global", "seasonal_influenza"),
            ("Measles - Global situation", "measles"),
            ("Mpox - African Region", "mpox"),
        ],
    )
    def test_real_who_titles_map_to_the_right_profile(self, label: str, expected: str) -> None:
        assert match_profile_key(label) == expected

    def test_longer_aliases_win(self) -> None:
        """'middle east respiratory' must beat the generic 'respiratory syndrome'."""
        assert match_profile_key("Middle East respiratory syndrome") == "hospital_amplified"

    @pytest.mark.parametrize(
        "label",
        [
            "Ebola virus disease \u2013 Uganda",  # en dash, as WHO often writes it
            "EBOLA DISEASE",  # upper case
            "Ebola/Marburg co-circulation",  # punctuation
        ],
    )
    def test_matching_survives_punctuation_and_case(self, label: str) -> None:
        assert match_profile_key(label) == "low_mobility_severe"

    @pytest.mark.parametrize("label", [None, "", "Unknown novel pathogen", "Nipah virus"])
    def test_unmatched_labels_return_none_rather_than_a_default(self, label: str | None) -> None:
        """An unmatched pathogen must not inherit respiratory parameters."""
        assert match_profile_key(label) is None
