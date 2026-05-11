from __future__ import annotations

from decimal import Decimal

from app.tax_facts import TaxFacts
from app.tax_registry import BracketTable, TaxTableRegistry, TaxYearProfile

from .types import (
    CreditResult,
    FederalResult,
    ItemizedBreakdown,
    SETaxResult,
)

_ZERO = Decimal("0")
_SE_NET_FACTOR = Decimal("0.9235")
_SS_RATE = Decimal("0.124")
_MEDICARE_RATE = Decimal("0.029")
_SE_DEDUCTION_FACTOR = Decimal("0.5")
_THOUSAND = Decimal("1000")
_ONE = Decimal("1")


class FederalEngine:
    def __init__(self, registry: TaxTableRegistry) -> None:
        self._registry = registry

    def compute(self, facts: TaxFacts) -> FederalResult:
        year = facts.tax_year
        filing_status = facts.filing_status

        salary1_annual = facts.salary1.annual
        salary2_annual = facts.salary2.annual if facts.salary2 else _ZERO
        w2_income = salary1_annual + salary2_annual

        additional_income = (
            facts.income_1099g
            + facts.income_1099nec
            + facts.income_1099int_div
            + facts.other_income
        )

        se_tax = self._self_employment_tax(facts.income_1099nec, year)
        pretax = facts.total_pretax
        gross_income = w2_income + additional_income

        agi_deductions = pretax + se_tax.deduction
        student_loan = self._student_loan_deduction(
            facts.student_loan_interest,
            gross_income - agi_deductions,
            filing_status,
            year,
        )
        agi_deductions += student_loan.amount
        agi = gross_income - agi_deductions

        profile = self._registry.profile("federal", year, filing_status)
        standard_deduction = profile.standard_deduction
        itemized = self._itemized(facts, year)

        use_itemized = itemized.total > standard_deduction
        deduction_used = itemized.total if use_itemized else standard_deduction

        taxable_income = max(_ZERO, agi - deduction_used)
        tax_before_credits = profile.brackets.tax_on(taxable_income)
        bracket_breakdown = profile.brackets.iter_breakdown(taxable_income)

        child_credit = self._child_tax_credit(facts, agi, filing_status, year)
        final_tax = max(_ZERO, tax_before_credits - child_credit.amount)

        return FederalResult(
            w2_income=w2_income,
            salary1_annual=salary1_annual,
            salary2_annual=salary2_annual,
            additional_income=additional_income,
            gross_income=gross_income,
            pretax_deductions=pretax,
            se_tax=se_tax,
            student_loan=student_loan,
            agi=agi,
            standard_deduction=standard_deduction,
            itemized=itemized,
            use_itemized=use_itemized,
            deduction_used=deduction_used,
            taxable_income=taxable_income,
            tax_before_credits=tax_before_credits,
            bracket_breakdown=bracket_breakdown,
            child_tax_credit=child_credit,
            final_tax=final_tax,
        )

    def _self_employment_tax(self, nec_income: Decimal, year: int) -> SETaxResult:
        if nec_income <= 0:
            return SETaxResult()
        se_earnings = nec_income * _SE_NET_FACTOR
        ss_wage_base = self._registry.federal_limit(year, "se_tax_ss_wage_base")
        ss_taxable = min(se_earnings, ss_wage_base)
        ss_tax = ss_taxable * _SS_RATE
        medicare_tax = se_earnings * _MEDICARE_RATE
        total = ss_tax + medicare_tax
        deduction = total * _SE_DEDUCTION_FACTOR
        return SETaxResult(
            se_income=se_earnings,
            ss_tax=ss_tax,
            medicare_tax=medicare_tax,
            total=total,
            deduction=deduction,
        )

    def _student_loan_deduction(
        self,
        interest_paid: Decimal,
        agi_for_phaseout: Decimal,
        filing_status: str,
        year: int,
    ) -> CreditResult:
        if interest_paid <= 0:
            return CreditResult(
                amount=_ZERO,
                explanation="No student loan interest entered",
            )
        max_cap = self._registry.federal_limit(year, "student_loan_max_deduction")
        max_deduction = min(interest_paid, max_cap)
        phase_out = self._registry.extra("federal", year, "student_loan_phase_out")
        start = phase_out["start"].get(filing_status, phase_out["start"]["single"])
        rng = phase_out["range"].get(filing_status, phase_out["range"]["single"])

        agi_f = float(agi_for_phaseout)
        start_f = float(start)
        if agi_for_phaseout <= start:
            return CreditResult(
                amount=max_deduction,
                explanation=(
                    f"Full deduction: AGI ${agi_f:,.0f} is below phase-out start of ${start_f:,}"
                ),
            )
        if agi_for_phaseout >= start + rng:
            return CreditResult(
                amount=_ZERO,
                explanation=(
                    f"No deduction: AGI ${agi_f:,.0f} exceeds phase-out limit of "
                    f"${float(start + rng):,}"
                ),
            )
        pct = (agi_for_phaseout - start) / rng
        reduced = max_deduction * (_ONE - pct)
        return CreditResult(
            amount=reduced,
            explanation=(
                f"Partially phased out: ${float(reduced):,.0f} deduction "
                f"(reduced {float(pct) * 100:.0f}%)"
            ),
        )

    def _itemized(self, facts: TaxFacts, year: int) -> ItemizedBreakdown:
        itm = facts.itemized
        salt_cap = self._registry.federal_limit(year, "salt_cap")
        salt_allowed = min(itm.salt, salt_cap)
        return ItemizedBreakdown(
            charitable=itm.charitable,
            mortgage_interest=itm.mortgage_interest,
            salt=salt_allowed,
            salt_original=itm.salt,
            salt_capped=itm.salt > salt_cap,
            medical=itm.medical,
            other=itm.other,
        )

    def _child_tax_credit(
        self,
        facts: TaxFacts,
        agi: Decimal,
        filing_status: str,
        year: int,
    ) -> CreditResult:
        ctc = self._registry.extra("federal", year, "child_tax_credit")
        base = (
            Decimal(facts.children_under_17) * ctc["under_17"]
            + Decimal(facts.other_dependents) * ctc["other_dependent"]
        )
        if base == 0:
            return CreditResult(
                amount=_ZERO,
                explanation="No dependents claimed",
            )
        threshold = ctc["phase_out_start"].get(
            filing_status, ctc["phase_out_start"]["single"]
        )
        agi_f = float(agi)
        threshold_f = float(threshold)
        if agi <= threshold:
            return CreditResult(
                amount=base,
                explanation=(
                    f"Full credit: AGI ${agi_f:,.0f} is below phase-out threshold of "
                    f"${threshold_f:,.0f}"
                ),
            )
        excess = agi - threshold
        phase_out_amount = (excess // _THOUSAND) * ctc["phase_out_rate"]
        final = max(_ZERO, base - phase_out_amount)
        phased_out = min(base, phase_out_amount)
        return CreditResult(
            amount=final,
            phased_out=phased_out,
            explanation=(
                f"Credit reduced by ${float(phase_out_amount):,.0f} due to AGI "
                f"${agi_f:,.0f} exceeding ${threshold_f:,.0f} threshold"
            ),
        )
