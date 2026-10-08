import pytest

from app.utils.role_filter import is_technical_role

TECHNICAL = [
    "Principal Software Engineer - Agent & Automation",
    "Senior Security Engineer - Corporate Security",
    "Staff Data Scientist",
    "iOS Developer",
    "Site Reliability Engineer",
    "DevOps Architect",
    "Machine Learning Engineer",
    "Senior Backend Developer",
    "Research Scientist, Alignment",
    "Platform Engineering Manager",
    "QA Automation Engineer",
    "Android Developer",
]

NON_TECHNICAL = [
    "Enterprise Account Executive - West",
    "Business Development Representative",
    "Director of Lifecycle Marketing",
    "Accounting Manager",
    "Accounts Payable Manager",
    "Head of People",
    "Copywriter",
    "General Counsel",
    # A technical word in a non-technical role — the negative pattern wins.
    "Sales Engineer",
    "Engineering Recruiter",
    "Technical Recruiter",
    "Data Science Recruiter",
]


@pytest.mark.parametrize("title", TECHNICAL)
def test_technical_titles_are_kept(title: str) -> None:
    assert is_technical_role(title) is True


@pytest.mark.parametrize("title", NON_TECHNICAL)
def test_non_technical_titles_are_dropped(title: str) -> None:
    assert is_technical_role(title) is False


@pytest.mark.parametrize("title", [None, "", "   "])
def test_missing_titles_are_dropped(title: str | None) -> None:
    assert is_technical_role(title) is False
