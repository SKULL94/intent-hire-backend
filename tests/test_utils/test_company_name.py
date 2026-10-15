from __future__ import annotations

import pytest

from app.utils.company_name import (
    clean_display_name,
    is_entity_code,
    is_staffing_firm,
)


class TestIsStaffingFirm:
    @pytest.mark.parametrize(
        "name",
        [
            "HuntingCube Recruitment Solutions",
            "Acumen360 Consulting & HR Solutions",
            "Guidance Placement Hiring For urgent hiring php java react",
            "Kruger NearShore LLC - Rekluti",
            "Recruitingbond",
            "ABC Manpower Services",
            "XYZ Staffing Pvt Ltd",
            "Talent Acquisition Partners",
        ],
    )
    def test_agencies_are_rejected(self, name):
        assert is_staffing_firm(name)

    @pytest.mark.parametrize(
        "name",
        [
            # Real employers that build software. "Consulting" alone must not
            # be enough to reject, or we lose genuine engineering shops.
            "Capco",
            "Nihilent",
            "Thoughtworks",
            "JS TechAlliance Consulting",
            "Unison Consulting",
            "Yudiz Solutions",
            "Robosoft Technologies",
            "Zomato",
        ],
    )
    def test_real_employers_survive(self, name):
        assert not is_staffing_firm(name)


class TestIsEntityCode:
    @pytest.mark.parametrize(
        "name", ["ADCI HYD 20 SEZ", "ADCI - Karnataka", "AWS India - BLR 14"]
    )
    def test_internal_codes_are_rejected(self, name):
        assert is_entity_code(name)

    @pytest.mark.parametrize("name", ["Amazon", "CGI", "InMobi", "HDFC ERGO"])
    def test_real_names_and_acronyms_survive(self, name):
        assert not is_entity_code(name)


class TestCleanDisplayName:
    def test_strips_truncated_dangling_word(self):
        # The feed truncated mid-phrase: "Aarms Solutions on<something>".
        assert clean_display_name("Aarms Solutions on") == "Aarms Solutions"

    def test_strips_legal_decoration(self):
        assert clean_display_name("SolGuruz Private Limited") == "SolGuruz"
        assert clean_display_name("iauro Systems Pvt. Ltd.") == "iauro Systems"
        assert clean_display_name("McAfee, Inc.") == "McAfee"

    def test_keeps_a_trailing_connector_from_dangling(self):
        # Regression: "Zino & Co." must not collapse to "Zino &".
        assert clean_display_name("Zino & Co.") == "Zino"

    def test_fixes_shouted_multiword_names(self):
        assert clean_display_name("MAXGEN TECHNOLOGIES PRIVATE LIMITED") == (
            "Maxgen Technologies"
        )

    @pytest.mark.parametrize("name", ["CGI", "InMobi", "iauro Systems", "Setu"])
    def test_leaves_good_names_alone(self, name):
        assert clean_display_name(name) == name

    def test_acronyms_are_not_title_cased(self):
        # Single-word all-caps is a brand, not feed shouting.
        assert clean_display_name("CGI") == "CGI"

    def test_returns_none_for_nothing_usable(self):
        assert clean_display_name("") is None
        assert clean_display_name(None) is None
        assert clean_display_name("   ---   ") is None
