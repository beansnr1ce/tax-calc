"""
Top-level tax calculation orchestration.

The federal pipeline lives in `app.federal_tax`. This module composes the
federal engine with the state engine and the (still-procedural) withholding
helpers, and exposes `TaxPipeline` plus a backwards-compatible
`calculate_all(facts)` shim.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .federal_tax import FederalEngine, FederalResult
from .state_tax import StateEngineRegistry
from .state_tax.states import register_overrides
from .tax_facts import TaxFacts, build_facts
from .tax_registry import FilesystemSource, TaxTableRegistry

_DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "tax_tables"


class TaxPipeline:
    """Compose federal + state + withholding into the legacy JSON dict."""

    def __init__(
        self,
        tax_tables: TaxTableRegistry,
        state_engines: StateEngineRegistry,
    ) -> None:
        self._tables = tax_tables
        self._engines = state_engines
        self._fed = FederalEngine(tax_tables)

    @property
    def tax_tables(self) -> TaxTableRegistry:
        return self._tables

    @property
    def state_engines(self) -> StateEngineRegistry:
        return self._engines

    def compute_federal(self, facts: TaxFacts) -> FederalResult:
        return self._fed.compute(facts)

    def calculate_all(self, facts: TaxFacts | Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(facts, TaxFacts):
            facts = build_facts(
                facts,
                tax_tables=self._tables,
                state_engines=self._engines,
            )

        fed = self._fed.compute(facts)
        federal_dict = fed.to_legacy_dict()
        state_dict = self._compute_state(facts, fed)
        withholding = calculate_withholding(
            facts, federal_dict, state_dict, registry=self._tables
        )

        return {
            "federal": federal_dict,
            "california": state_dict,
            "state": state_dict,
            "withholding": withholding,
            "summary": {
                "tax_year": facts.tax_year,
                "filing_status": facts.filing_status,
                "gross_income": federal_dict["gross_income"],
                "federal_tax": federal_dict["final_tax"],
                "se_tax": federal_dict["se_tax"]["total"],
                "california_tax": state_dict["final_tax"],
                "ca_sdi": state_dict["sdi"]["tax"],
                "total_tax": withholding["totals"]["grand_total"],
            },
        }

    def _compute_state(
        self, facts: TaxFacts, fed: FederalResult
    ) -> dict[str, Any]:
        year = facts.tax_year
        state_code = facts.state
        fed_itm = fed.itemized.total if fed.use_itemized else Decimal("0")
        inp = facts.to_state_input(
            federal_agi=fed.agi,
            federal_taxable_income=fed.taxable_income,
            federal_itemized=fed_itm,
        )
        engine = self._engines.get(state_code)
        result = engine.compute(inp)

        sdi_value = float(result.addons.get("sdi", Decimal("0")))
        mhst_value = float(result.surcharges.get("mhst", Decimal("0")))
        exemption_value = float(result.credits.get("exemption", Decimal("0")))
        dependent_value = float(result.credits.get("dependent", Decimal("0")))

        sdi_block: dict[str, Any] = {
            "tax": sdi_value,
            "rate": 0,
            "wage_base": 0,
            "taxable_wages": 0,
        }
        if state_code == "CA":
            sdi_extra = self._tables.extra(state_code, year, "sdi")
            sdi_block["rate"] = float(sdi_extra["rate"]) * 100
            sdi_block["wage_base"] = float(sdi_extra["wage_base"])
            sdi_block["taxable_wages"] = min(
                float(inp.wages_w2), float(sdi_extra["wage_base"])
            )

        return {
            "agi": float(result.starting_income),
            "standard_deduction": float(result.standard_deduction),
            "itemized_deduction": _ca_itemized_legacy(facts),
            "use_itemized": result.use_itemized,
            "deduction_used": float(result.deduction_used),
            "taxable_income": float(result.taxable_income),
            "tax_before_credits": float(result.tax_before_credits),
            "bracket_breakdown": [],
            "mental_health_tax": mhst_value,
            "exemption_credit": exemption_value,
            "dependent_credit": dependent_value,
            "total_credits": exemption_value + dependent_value,
            "final_tax": float(result.final_tax),
            "sdi": sdi_block,
        }


def _ca_itemized_legacy(facts: TaxFacts) -> dict[str, Any]:
    """California-side itemized dict (matches legacy tax_type='california' path).

    CA mirrors the federal salt heuristic of ~50% being property tax.
    No SALT cap; no salt_capped/salt_original keys.
    """
    itm = facts.itemized
    charitable = float(itm.charitable)
    mortgage_interest = float(itm.mortgage_interest)
    salt = float(itm.salt)
    medical = float(itm.medical)
    other = float(itm.other)
    property_tax_estimate = salt * 0.5
    breakdown = {
        "charitable": charitable,
        "mortgage_interest": mortgage_interest,
        "medical": medical,
        "other": other,
        "salt": property_tax_estimate,
    }
    total = charitable + mortgage_interest + property_tax_estimate + medical + other
    return {"total": round(total, 2), "breakdown": breakdown}


# ---------------------------------------------------------------------------
# Withholding (procedural; still legacy float-based — see Candidate-2 follow-up)
# ---------------------------------------------------------------------------


def _format_due_dates(year: int, registry: TaxTableRegistry) -> list:
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    dates = registry.quarterly_due_dates(year)
    return [
        (f"Q{i + 1}", f"{months[d.month - 1]} {d.day}, {d.year}")
        for i, d in enumerate(dates)
    ]


def calculate_withholding(facts, federal_result, ca_result, *, registry: TaxTableRegistry):
    year = facts.tax_year
    filing_status = facts.filing_status
    dual_income = facts.dual_income

    salary1_annual = float(facts.salary1.annual)
    salary1_periods = facts.salary1.periods_per_year

    salary2_annual = float(facts.salary2.annual) if facts.salary2 else 0.0
    salary2_periods = facts.salary2.periods_per_year if facts.salary2 else 0

    total_w2_income = salary1_annual + salary2_annual
    total_federal = federal_result["final_tax"] + federal_result["se_tax"]["total"]
    total_ca = ca_result["final_tax"]
    total_sdi = ca_result["sdi"]["tax"]

    additional_income = federal_result["additional_income"]

    itemizing = federal_result["use_itemized"]
    extra_deduction = 0
    if itemizing:
        extra_deduction = (
            federal_result["itemized_deduction"]["total"]
            - federal_result["standard_deduction"]
        )

    child_credit = federal_result["child_tax_credit"]["total"]

    if dual_income and salary2_annual > 0:
        salary1_pct = salary1_annual / total_w2_income
        salary2_pct = salary2_annual / total_w2_income
    else:
        salary1_pct = 1.0
        salary2_pct = 0

    w4_guidance = []
    de4_guidance = []

    w4_guidance.append(
        generate_w4_guidance(
            salary_num=1,
            annual_salary=salary1_annual,
            pay_periods=salary1_periods,
            filing_status=filing_status,
            dual_income=dual_income,
            additional_income=additional_income * salary1_pct,
            extra_deduction=extra_deduction * salary1_pct,
            child_credit=child_credit * salary1_pct,
            total_federal_tax=total_federal * salary1_pct,
            se_tax=federal_result["se_tax"]["total"] * salary1_pct,
            registry=registry,
        )
    )
    de4_guidance.append(
        generate_de4_guidance(
            salary_num=1,
            annual_salary=salary1_annual,
            pay_periods=salary1_periods,
            filing_status=filing_status,
            total_ca_tax=total_ca * salary1_pct,
            num_dependents=facts.children_under_17 + facts.other_dependents,
            registry=registry,
        )
    )

    if dual_income and salary2_annual > 0:
        w4_guidance.append(
            generate_w4_guidance(
                salary_num=2,
                annual_salary=salary2_annual,
                pay_periods=salary2_periods,
                filing_status=filing_status,
                dual_income=True,
                additional_income=additional_income * salary2_pct,
                extra_deduction=extra_deduction * salary2_pct,
                child_credit=child_credit * salary2_pct,
                total_federal_tax=total_federal * salary2_pct,
                se_tax=federal_result["se_tax"]["total"] * salary2_pct,
                registry=registry,
            )
        )
        de4_guidance.append(
            generate_de4_guidance(
                salary_num=2,
                annual_salary=salary2_annual,
                pay_periods=salary2_periods,
                filing_status=filing_status,
                total_ca_tax=total_ca * salary2_pct,
                num_dependents=0,
                registry=registry,
            )
        )

    quarterly_guidance = None
    if additional_income > 0:
        quarterly_guidance = generate_quarterly_guidance(
            additional_income=additional_income,
            se_tax=federal_result["se_tax"]["total"],
            tax_year=year,
            registry=registry,
        )

    return {
        "w4_guidance": w4_guidance,
        "de4_guidance": de4_guidance,
        "quarterly_guidance": quarterly_guidance,
        "totals": {
            "federal_income_tax": round(federal_result["final_tax"], 2),
            "self_employment_tax": round(federal_result["se_tax"]["total"], 2),
            "total_federal": round(total_federal, 2),
            "california_tax": round(total_ca, 2),
            "ca_sdi": round(total_sdi, 2),
            "grand_total": round(total_federal + total_ca + total_sdi, 2),
        },
    }


def generate_w4_guidance(
    salary_num,
    annual_salary,
    pay_periods,
    filing_status,
    dual_income,
    additional_income,
    extra_deduction,
    child_credit,
    total_federal_tax,
    se_tax,
    *,
    registry: TaxTableRegistry,
):
    status_map = {
        "single": "Single or Married filing separately",
        "married_jointly": "Married filing jointly",
        "head_of_household": "Head of household",
    }
    guidance = {
        "salary_num": salary_num,
        "annual_salary": round(annual_salary, 2),
        "step1": {
            "filing_status": status_map.get(filing_status, "Single"),
            "explanation": "Check the box matching your expected filing status for the tax year.",
        },
        "step2": {
            "check_box": dual_income and filing_status == "married_jointly",
            "explanation": "Check this box if you are married filing jointly AND both spouses work. This adjusts withholding to account for the higher combined tax bracket.",
        },
        "step3": {
            "amount": round(child_credit, 0),
            "explanation": f"Enter ${child_credit:,.0f} for dependents. This is your Child Tax Credit amount that reduces withholding.",
        },
        "step4a": {
            "amount": round(additional_income, 0),
            "explanation": f"Enter ${additional_income:,.0f} for other income (1099s, etc.). This ensures tax is withheld on income not subject to regular withholding.",
        },
        "step4b": {
            "amount": round(max(0, extra_deduction), 0),
            "explanation": f"Enter ${max(0, extra_deduction):,.0f} for deductions exceeding standard deduction. Only enter if you plan to itemize.",
        },
    }
    estimated_withholding = estimate_standard_withholding(
        annual_salary, filing_status, dual_income, registry=registry
    )
    tax_shortfall = total_federal_tax - estimated_withholding
    tax_shortfall += se_tax
    step_adjustments = (
        child_credit
        - additional_income * 0.22
        + extra_deduction * 0.22
    )
    extra_withholding_per_pay = max(0, (tax_shortfall + step_adjustments) / pay_periods)
    guidance["step4c"] = {
        "amount": round(extra_withholding_per_pay, 0),
        "explanation": f"Enter ${extra_withholding_per_pay:,.0f} extra per paycheck to ensure sufficient withholding. This accounts for SE tax and any underwithholding from multiple income sources.",
    }
    return guidance


def generate_de4_guidance(
    salary_num,
    annual_salary,
    pay_periods,
    filing_status,
    total_ca_tax,
    num_dependents,
    *,
    registry: TaxTableRegistry,
):
    status_map = {
        "single": "Single or Married (with two or more incomes)",
        "married_jointly": "Married (one income)",
        "head_of_household": "Head of Household",
    }
    base_allowances = 1
    if filing_status == "married_jointly":
        base_allowances = 2
    total_allowances = base_allowances + num_dependents
    estimated_ca_withholding = estimate_ca_withholding(
        annual_salary, total_allowances, registry=registry
    )
    withholding_shortfall = total_ca_tax - estimated_ca_withholding
    extra_per_pay = max(0, withholding_shortfall / pay_periods)
    return {
        "salary_num": salary_num,
        "annual_salary": round(annual_salary, 2),
        "filing_status": status_map.get(filing_status, "Single"),
        "filing_status_explanation": "Select the filing status that matches your tax return.",
        "allowances": total_allowances,
        "allowances_explanation": f"Claim {total_allowances} allowance(s): {base_allowances} for yourself"
        + (f" + {num_dependents} for dependents" if num_dependents > 0 else ""),
        "additional_withholding": round(extra_per_pay, 0),
        "additional_withholding_explanation": f"Enter ${extra_per_pay:,.0f} additional withholding per paycheck to ensure you meet your California tax obligation.",
    }


def estimate_standard_withholding(
    annual_salary, filing_status, dual_income, *, registry: TaxTableRegistry
):
    fed_profile = registry.profile("federal", 2025, filing_status)
    std_deduction = float(fed_profile.standard_deduction)
    if dual_income and filing_status == "married_jointly":
        std_deduction = std_deduction / 2
    taxable = max(0.0, annual_salary - std_deduction)
    return float(fed_profile.brackets.tax_on(Decimal(str(taxable))))


def estimate_ca_withholding(annual_salary, allowances, *, registry: TaxTableRegistry):
    allowance_value = 4800
    taxable = max(0.0, annual_salary - (allowances * allowance_value))
    ca_profile = registry.profile("CA", 2025, "single")
    return float(ca_profile.brackets.tax_on(Decimal(str(taxable))))


def generate_quarterly_guidance(
    additional_income, se_tax, tax_year, *, registry: TaxTableRegistry
):
    federal_on_additional = additional_income * 0.22
    total_quarterly_federal = federal_on_additional + se_tax
    ca_on_additional = additional_income * 0.093
    quarterly_federal = total_quarterly_federal / 4
    quarterly_ca = ca_on_additional / 4
    due_dates = _format_due_dates(tax_year, registry)
    return {
        "has_1099_income": True,
        "annual_federal_estimate": round(total_quarterly_federal, 2),
        "annual_ca_estimate": round(ca_on_additional, 2),
        "quarterly_federal": round(quarterly_federal, 2),
        "quarterly_ca": round(quarterly_ca, 2),
        "due_dates": due_dates,
        "federal_form": "Form 1040-ES",
        "ca_form": "Form 540-ES",
        "explanation": "If you have significant 1099 income, you may need to make quarterly estimated tax payments to avoid underpayment penalties. Pay quarterly if you expect to owe $1,000+ federal or $500+ California.",
    }


# ---------------------------------------------------------------------------
# Backwards-compat free function — delegates to a lazily-built default pipeline.
# Production callers should construct TaxPipeline explicitly (see app/main.py).
# ---------------------------------------------------------------------------

_default_pipeline: TaxPipeline | None = None


def _build_default_pipeline() -> TaxPipeline:
    root = Path(os.environ.get("TAX_DATA_ROOT", _DEFAULT_DATA_ROOT))
    tables = TaxTableRegistry(source=FilesystemSource(root))
    engines = StateEngineRegistry(registry=tables)
    register_overrides(engines)
    return TaxPipeline(tables, engines)


def calculate_all(facts):
    """Backwards-compat entry point. Prefer constructing a TaxPipeline directly."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = _build_default_pipeline()
    return _default_pipeline.calculate_all(facts)
