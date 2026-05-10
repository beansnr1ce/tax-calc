from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from app.tax_registry import TaxYearProfile

from ..engines import StandardStateEngine
from ..types import StateTaxInput


class CaliforniaEngine(StandardStateEngine):
    def compute_surcharges(
        self, inp: StateTaxInput, profile: TaxYearProfile, taxable_income: Decimal
    ) -> Mapping[str, Decimal]:
        """MHST is part of CA income tax liability — added to final_tax."""
        mh_threshold = self.registry.extra("CA", inp.year, "mental_health_threshold")
        mh_rate = self.registry.extra("CA", inp.year, "mental_health_rate")
        mhst = (
            (taxable_income - mh_threshold) * mh_rate
            if taxable_income > mh_threshold
            else Decimal("0")
        )
        return {"mhst": mhst}

    def compute_addons(
        self, inp: StateTaxInput, profile: TaxYearProfile, taxable_income: Decimal
    ) -> Mapping[str, Decimal]:
        """SDI is a payroll-side item — separate from income tax liability."""
        sdi = self.registry.extra("CA", inp.year, "sdi")
        sdi_taxable_wages = min(inp.wages_w2, sdi["wage_base"])
        sdi_tax = sdi_taxable_wages * sdi["rate"]
        return {"sdi": sdi_tax}

    def compute_credits(
        self, inp: StateTaxInput, profile: TaxYearProfile, taxable_income: Decimal
    ) -> Mapping[str, Decimal]:
        exemption_table = self.registry.extra("CA", inp.year, "exemption_credit")
        exemption = exemption_table[inp.filing_status]
        per_dep = self.registry.extra("CA", inp.year, "dependent_exemption_credit")
        dependent_credit = per_dep * inp.dependents
        return {"exemption": exemption, "dependent": dependent_credit}
