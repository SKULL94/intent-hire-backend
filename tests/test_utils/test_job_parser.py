from __future__ import annotations

import pytest

from app.utils.job_parser import (
    detect_technologies,
    normalize_location,
    parse_min_years,
)


class TestDetectTechnologies:
    def test_flutter_in_title_outranks_body(self):
        from_title = detect_technologies("Flutter Developer", "we use python")
        assert from_title["flutter"] == 0.95
        assert from_title["python"] == 0.7

    def test_dart_does_not_match_dartboard(self):
        assert "dart" not in detect_technologies("Pub Manager", "run the dartboard league")

    def test_java_does_not_match_javascript(self):
        techs = detect_technologies("Frontend Engineer", "strong JavaScript skills")
        assert "javascript" in techs
        assert "java" not in techs

    def test_react_native_is_not_plain_react(self):
        techs = detect_technologies("React Native Developer", "")
        assert "react-native" in techs
        assert "react" not in techs

    def test_go_only_matches_unambiguous_spellings(self):
        # "go" is too common a word to match bare.
        assert "golang" not in detect_technologies("Engineer", "we go fast and ship")
        assert "golang" in detect_technologies("Engineer", "experience with golang")

    def test_empty_input_is_empty_not_an_error(self):
        assert detect_technologies(None, None) == {}


class TestParseMinYears:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("3-5 years of experience", 3),
            ("3 to 5 years", 3),
            ("minimum 4 years experience", 4),
            ("at least 2 years", 2),
            ("5+ years", 5),
            ("7 years of relevant experience", 7),
            ("2 yrs experience", 2),
        ],
    )
    def test_extracts_the_lower_bound(self, text, expected):
        assert parse_min_years(text) == expected

    def test_ignores_implausible_numbers(self):
        # Company age, not a requirement.
        assert parse_min_years("25 years in business, serving clients") is None

    def test_returns_none_when_unstated(self):
        assert parse_min_years("Looking for a passionate Flutter developer") is None
        assert parse_min_years(None) is None


class TestNormalizeLocation:
    @pytest.mark.parametrize(
        "raw",
        ["Delhi, India", "New Delhi", "Noida, Uttar Pradesh", "Gurgaon, Haryana",
         "Gurugram", "Ghaziabad", "Faridabad", "Greater Noida"],
    )
    def test_ncr_satellite_towns_all_map_to_delhi_ncr(self, raw):
        # People search "Delhi NCR", not "Ghaziabad".
        assert normalize_location(raw)[0] == "delhi_ncr"

    def test_bengaluru_spellings(self):
        assert normalize_location("Bangalore")[0] == "bengaluru"
        assert normalize_location("Bengaluru, Karnataka")[0] == "bengaluru"

    def test_kochi_is_not_ncr(self):
        # Regression: passing the description into this function tagged a
        # Kochi posting as delhi_ncr because its body mentioned Delhi.
        assert normalize_location("Kochi, Ernakulam")[0] != "delhi_ncr"

    def test_remote_is_independent_of_city(self):
        key, remote = normalize_location("Remote, Delhi")
        assert key == "delhi_ncr"
        assert remote is True

    def test_remote_without_a_city(self):
        assert normalize_location("Remote") == ("remote", True)
        assert normalize_location("Work from home")[1] is True

    def test_unknown_location_is_none_not_a_guess(self):
        assert normalize_location("Reykjavik, Iceland") == (None, False)
        assert normalize_location(None) == (None, False)
