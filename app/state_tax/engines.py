from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from app.tax_registry import TaxTableRegistry, TaxYearProfile

from .types import StateTaxInput, StateTaxResult


class NullStateEngine:
    def __init__(self, jurisdiction: str):
        self.jurisdiction = jurisdiction

    def compute(self, inp: StateTaxInput) -> StateTaxResult:
        return StateTaxResult(jurisdiction=self.jurisdiction)


class StandardStateEngine:
    def __init__(self, jurisdiction: str, registry: TaxTableRegistry):
        self.jurisdiction = jurisdiction
        self.registry = registry

    def compute(self, inp: StateTaxInput) -> StateTaxResult:
        profile = self.registry.profile(self.jurisdiction, inp.year, inp.filing_status)
        starting = self.compute_starting_income(inp, profile)
        std, itm, use_itm = self.compute_deductions(inp, profile)
        deduction = itm if use_itm else std
        taxable = max(Decimal("0"), starting - deduction)
        tax = self.apply_brackets(taxable, profile)
        credits = self.compute_credits(inp, profile, taxable)
        surcharges = self.compute_surcharges(inp, profile, taxable)
        addons = self.compute_addons(inp, profile, taxable)
        final = max(
            Decimal("0"),
            tax + sum(surcharges.values(), Decimal("0")) - sum(credits.values(), Decimal("0")),
        )
        return StateTaxResult(
            jurisdiction=self.jurisdiction,
            starting_income=starting,
            standard_deduction=std,
            itemized_deduction=itm,
            use_itemized=use_itm,
            deduction_used=deduction,
            taxable_income=taxable,
            tax_before_credits=tax,
            credits=credits,
            surcharges=surcharges,
            addons=addons,
            final_tax=final,
        )

    def compute_starting_income(
        self, inp: StateTaxInput, profile: TaxYearProfile
    ) -> Decimal:
        if profile.starting_point == "federal_taxable":
            return inp.federal_taxable_income
        if profile.starting_point == "gross":
            return inp.wages_w2 + inp.self_employment_income
        return inp.federal_agi

    def compute_deductions(
        self, inp: StateTaxInput, profile: TaxYearProfile
    ) -> tuple[Decimal, Decimal, bool]:
        std = profile.standard_deduction
        if not profile.allows_itemized:
            return std, Decimal("0"), False
        itm = inp.federal_itemized if profile.itemized_source == "federal" else Decimal("0")
        return std, itm, itm > std

    def apply_brackets(self, taxable: Decimal, profile: TaxYearProfile) -> Decimal:
        return profile.brackets.tax_on(taxable)

    def compute_credits(
        self, inp: StateTaxInput, profile: TaxYearProfile, taxable_income: Decimal
    ) -> Mapping[str, Decimal]:
        return {}

    def compute_addons(
        self, inp: StateTaxInput, profile: TaxYearProfile, taxable_income: Decimal
    ) -> Mapping[str, Decimal]:
        return {}

    def compute_surcharges(
        self, inp: StateTaxInput, profile: TaxYearProfile, taxable_income: Decimal
    ) -> Mapping[str, Decimal]:
        return {}
