from __future__ import annotations

from app.collectors.ats.ashby import AshbyAdapter
from app.collectors.ats.base import ATSAdapter
from app.collectors.ats.greenhouse import GreenhouseAdapter
from app.collectors.ats.lever import LeverAdapter
from app.collectors.ats.smartrecruiters import SmartRecruitersAdapter
from app.collectors.ats.workable import WorkableAdapter

ADAPTERS: dict[str, ATSAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "workable": WorkableAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),
}


def get_adapter(ats_type: str | None) -> ATSAdapter | None:
    if not ats_type:
        return None
    return ADAPTERS.get(ats_type.lower())
