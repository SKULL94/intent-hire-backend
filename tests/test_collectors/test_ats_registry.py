from __future__ import annotations

import pytest

from app.collectors.ats.registry import ADAPTERS, get_adapter


def test_known_adapters_registered():
    for name in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters"):
        assert name in ADAPTERS
        assert ADAPTERS[name].ats_name() == name


def test_get_adapter_case_insensitive():
    assert get_adapter("Greenhouse") is ADAPTERS["greenhouse"]


@pytest.mark.parametrize("value", [None, "", "other", "workday"])
def test_get_adapter_returns_none_for_unknown(value):
    assert get_adapter(value) is None
