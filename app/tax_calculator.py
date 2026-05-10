"""
Core tax calculation engine for federal and California taxes.
Provides W-4 and DE 4 form guidance.
"""

import os
from pathlib import Path

from decimal import Decimal as _Decimal

from .state_tax import StateEngineRegistry
from .state_tax.states import register_overrides
from .tax_facts import TaxFacts as _TaxFacts
from .tax_registry import BracketTable, FilesystemSource, TaxTableRegistry

_DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "tax_tables"
_registry: TaxTableRegistry | None = None
_engines: StateEngineRegistry | None = None


def _get_registry() -> TaxTableRegistry:
    global _registry
    if _registry is None:
        root = Path(os.environ.get("TAX_DATA_ROOT", _DEFAULT_DATA_ROOT))
        _registry = TaxTableRegistry(source=FilesystemSource(root))
    return _registry


def _get_engines() -> StateEngineRegistry:
    global _engines
    if _engines is None:
        _engines = StateEngineRegistry(registry=_get_registry())
        register_overrides(_engines)
    return _engines


def _f(value) -> float:
    """Convert Decimal (or any numeric) to float at the legacy boundary."""
    return float(value)


def _format_due_dates(year: int) -> list:
    """Format registry's date tuples as [(label, formatted_date), ...] for template."""
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    dates = _get_registry().quarterly_due_dates(year)
    return [
        (f"Q{i + 1}", f"{months[d.month - 1]} {d.day}, {d.year}")
        for i, d in enumerate(dates)
    ]


def calculate_bracket_tax(taxable_income, bracket_table: BracketTable):
    """
    Calculate tax using progressive brackets (floor-form).
    Returns (total_tax, bracket_breakdown).
    """
    tax = 0
    breakdown = []
    brackets = bracket_table.brackets

    for i, bracket in enumerate(brackets):
        floor = _f(bracket.floor)
        rate = _f(bracket.rate)
        if taxable_income <= floor:
            break
        next_floor = _f(brackets[i + 1].floor) if i + 1 < len(brackets) else None
        top = min(taxable_income, next_floor) if next_floor is not None else taxable_income
        taxable_in_bracket = top - floor
        if taxable_in_bracket > 0:
            tax_in_bracket = taxable_in_bracket * rate
            tax += tax_in_bracket
            breakdown.append({
                'bracket_start': floor,
                'bracket_end': next_floor if next_floor is not None else 'unlimited',
                'rate': rate * 100,
                'taxable_amount': taxable_in_bracket,
                'tax': tax_in_bracket
            })

    return tax, breakdown


def calculate_self_employment_tax(nec_income, year):
    """
    Calculate self-employment tax on 1099-NEC income.
    SE tax = 15.3% (12.4% SS + 2.9% Medicare) on 92.35% of net SE income.
    """
    if nec_income <= 0:
        return {'total': 0, 'ss_tax': 0, 'medicare_tax': 0, 'se_income': 0, 'deduction': 0}

    # Net self-employment earnings (92.35% of gross)
    se_earnings = nec_income * 0.9235
    ss_wage_base = _f(_get_registry().federal_limit(year, "se_tax_ss_wage_base"))

    # Social Security portion (12.4% up to wage base)
    ss_taxable = min(se_earnings, ss_wage_base)
    ss_tax = ss_taxable * 0.124

    # Medicare portion (2.9% on all SE earnings)
    medicare_tax = se_earnings * 0.029

    # Additional Medicare tax (0.9% on earnings over $200k single / $250k married)
    # Simplified: not implementing additional Medicare here

    total_se_tax = ss_tax + medicare_tax

    # Deduction: 50% of SE tax is deductible for income tax purposes
    se_deduction = total_se_tax * 0.5

    return {
        'total': round(total_se_tax, 2),
        'ss_tax': round(ss_tax, 2),
        'medicare_tax': round(medicare_tax, 2),
        'se_income': round(se_earnings, 2),
        'deduction': round(se_deduction, 2)
    }


def calculate_child_tax_credit(children_under_17, other_dependents, agi, filing_status, year=2025):
    """
    Calculate Child Tax Credit with phase-out.
    $2,000 per child under 17, $500 per other dependent.
    Phase-out: $50 reduction per $1,000 over threshold.
    """
    ctc = _get_registry().extra("federal", year, "child_tax_credit")
    base_credit = (children_under_17 * _f(ctc["under_17"]) +
                   other_dependents * _f(ctc["other_dependent"]))

    if base_credit == 0:
        return {'total': 0, 'phased_out': 0, 'explanation': 'No dependents claimed'}

    threshold = _f(ctc["phase_out_start"].get(filing_status, ctc["phase_out_start"]["single"]))

    if agi <= threshold:
        return {
            'total': base_credit,
            'phased_out': 0,
            'explanation': f'Full credit: AGI ${agi:,.0f} is below phase-out threshold of ${threshold:,.0f}'
        }

    # Calculate phase-out
    excess = agi - threshold
    phase_out_amount = (excess // 1000) * _f(ctc["phase_out_rate"])
    final_credit = max(0, base_credit - phase_out_amount)

    return {
        'total': final_credit,
        'phased_out': min(base_credit, phase_out_amount),
        'explanation': f'Credit reduced by ${phase_out_amount:,.0f} due to AGI ${agi:,.0f} exceeding ${threshold:,.0f} threshold'
    }


def calculate_student_loan_deduction(interest_paid, agi, filing_status, year):
    """
    Calculate student loan interest deduction with phase-out.
    Max $2,500, phases out at higher incomes.
    """
    if interest_paid <= 0:
        return {'deduction': 0, 'explanation': 'No student loan interest entered'}

    reg = _get_registry()
    max_deduction = min(interest_paid, _f(reg.federal_limit(year, "student_loan_max_deduction")))
    phase_out = reg.extra("federal", year, "student_loan_phase_out")
    phase_out_start = _f(phase_out["start"].get(filing_status, phase_out["start"]["single"]))
    phase_out_range = _f(phase_out["range"].get(filing_status, phase_out["range"]["single"]))

    if agi <= phase_out_start:
        return {
            'deduction': max_deduction,
            'explanation': f'Full deduction: AGI ${agi:,.0f} is below phase-out start of ${phase_out_start:,}'
        }

    if agi >= phase_out_start + phase_out_range:
        return {
            'deduction': 0,
            'explanation': f'No deduction: AGI ${agi:,.0f} exceeds phase-out limit of ${phase_out_start + phase_out_range:,}'
        }

    # Partial phase-out
    phase_out_pct = (agi - phase_out_start) / phase_out_range
    reduced_deduction = max_deduction * (1 - phase_out_pct)

    return {
        'deduction': round(reduced_deduction, 2),
        'explanation': f'Partially phased out: ${reduced_deduction:,.0f} deduction (reduced {phase_out_pct*100:.0f}%)'
    }


def calculate_federal_tax(facts):
    """
    Calculate complete federal tax liability.
    Accepts a TaxFacts value object.
    """
    year = facts.tax_year
    filing_status = facts.filing_status

    salary1_annual = float(facts.salary1.annual)
    salary2_annual = float(facts.salary2.annual) if facts.salary2 else 0.0
    w2_income = salary1_annual + salary2_annual

    income_1099g = float(facts.income_1099g)
    income_1099nec = float(facts.income_1099nec)
    income_1099int_div = float(facts.income_1099int_div)
    other_income = float(facts.other_income)
    total_additional_income = income_1099g + income_1099nec + income_1099int_div + other_income

    se_tax = calculate_self_employment_tax(income_1099nec, year)

    total_pretax = float(facts.total_pretax)

    gross_income = w2_income + total_additional_income
    agi_deductions = total_pretax + se_tax['deduction']

    student_loan = calculate_student_loan_deduction(
        float(facts.student_loan_interest),
        gross_income - agi_deductions,
        filing_status,
        year
    )
    agi_deductions += student_loan['deduction']

    agi = gross_income - agi_deductions

    fed_profile = _get_registry().profile("federal", year, filing_status)
    standard_deduction = _f(fed_profile.standard_deduction)
    itemized = _itemized_for_legacy(facts, 'federal', year)

    use_itemized = itemized['total'] > standard_deduction
    deduction_amount = itemized['total'] if use_itemized else standard_deduction

    taxable_income = max(0, agi - deduction_amount)
    tax, bracket_breakdown = calculate_bracket_tax(taxable_income, fed_profile.brackets)

    child_credit = calculate_child_tax_credit(
        facts.children_under_17,
        facts.other_dependents,
        agi,
        filing_status,
        year
    )

    final_tax = max(0, tax - child_credit['total'])

    return {
        'gross_income': round(gross_income, 2),
        'w2_income': round(w2_income, 2),
        'salary1_annual': round(salary1_annual, 2),
        'salary2_annual': round(salary2_annual, 2),
        'additional_income': round(total_additional_income, 2),
        'pretax_deductions': round(total_pretax, 2),
        'se_tax_deduction': round(se_tax['deduction'], 2),
        'student_loan_deduction': student_loan,
        'agi': round(agi, 2),
        'standard_deduction': standard_deduction,
        'itemized_deduction': itemized,
        'use_itemized': use_itemized,
        'deduction_used': round(deduction_amount, 2),
        'taxable_income': round(taxable_income, 2),
        'tax_before_credits': round(tax, 2),
        'bracket_breakdown': bracket_breakdown,
        'child_tax_credit': child_credit,
        'final_tax': round(final_tax, 2),
        'se_tax': se_tax
    }



def _itemized_for_legacy(facts, tax_type, year):
    """Adapter: build the legacy itemized dict shape from TaxFacts."""
    return calculate_itemized_deductions(
        {
            'charitable': float(facts.itemized.charitable),
            'mortgage_interest': float(facts.itemized.mortgage_interest),
            'salt': float(facts.itemized.salt),
            'medical': float(facts.itemized.medical),
            'other': float(facts.itemized.other),
        },
        tax_type,
        year,
    )


def calculate_itemized_deductions(deductions, tax_type, year=2025):
    """
    Calculate itemized deductions for federal or California.
    """
    if not deductions:
        return {'total': 0, 'breakdown': {}}

    charitable = deductions.get('charitable', 0) or 0
    mortgage_interest = deductions.get('mortgage_interest', 0) or 0
    salt = deductions.get('salt', 0) or 0
    medical = deductions.get('medical', 0) or 0
    other = deductions.get('other', 0) or 0

    breakdown = {
        'charitable': charitable,
        'mortgage_interest': mortgage_interest,
        'medical': medical,
        'other': other
    }

    if tax_type == 'federal':
        salt_cap = _f(_get_registry().federal_limit(year, "salt_cap"))
        salt_allowed = min(salt, salt_cap)
        breakdown['salt'] = salt_allowed
        breakdown['salt_capped'] = salt > salt_cap
        breakdown['salt_original'] = salt
    else:
        # California has no SALT cap (but doesn't allow SALT deduction for CA taxes paid)
        # CA allows property tax but not state income tax
        property_tax_estimate = salt * 0.5  # Rough estimate, assuming half is property tax
        breakdown['salt'] = property_tax_estimate

    total = sum(breakdown.get(k, 0) for k in ['charitable', 'mortgage_interest', 'salt', 'medical', 'other'])

    return {'total': round(total, 2), 'breakdown': breakdown}


def calculate_withholding(facts, federal_result, ca_result):
    """
    Calculate current withholding and provide W-4/DE 4 guidance.
    Accepts a TaxFacts value object.
    """
    year = facts.tax_year
    filing_status = facts.filing_status
    dual_income = facts.dual_income

    salary1_annual = float(facts.salary1.annual)
    salary1_periods = facts.salary1.periods_per_year

    salary2_annual = float(facts.salary2.annual) if facts.salary2 else 0.0
    salary2_periods = facts.salary2.periods_per_year if facts.salary2 else 0

    total_w2_income = salary1_annual + salary2_annual

    # Total tax liabilities
    total_federal = federal_result['final_tax'] + federal_result['se_tax']['total']
    total_ca = ca_result['final_tax']
    total_sdi = ca_result['sdi']['tax']

    # Calculate W-4 guidance for each salary
    w4_guidance = []
    de4_guidance = []

    # Additional income from 1099s
    additional_income = federal_result['additional_income']

    # Determine if itemizing is beneficial
    itemizing = federal_result['use_itemized']
    extra_deduction = 0
    if itemizing:
        extra_deduction = federal_result['itemized_deduction']['total'] - federal_result['standard_deduction']

    # Child tax credit amount
    child_credit = federal_result['child_tax_credit']['total']

    # Calculate allocation for dual income
    if dual_income and salary2_annual > 0:
        salary1_pct = salary1_annual / total_w2_income
        salary2_pct = salary2_annual / total_w2_income
    else:
        salary1_pct = 1.0
        salary2_pct = 0

    # W-4 for Salary 1
    w4_1 = generate_w4_guidance(
        salary_num=1,
        annual_salary=salary1_annual,
        pay_periods=salary1_periods,
        filing_status=filing_status,
        dual_income=dual_income,
        additional_income=additional_income * salary1_pct,
        extra_deduction=extra_deduction * salary1_pct,
        child_credit=child_credit * salary1_pct,
        total_federal_tax=total_federal * salary1_pct,
        se_tax=federal_result['se_tax']['total'] * salary1_pct
    )
    w4_guidance.append(w4_1)

    # DE 4 for Salary 1
    de4_1 = generate_de4_guidance(
        salary_num=1,
        annual_salary=salary1_annual,
        pay_periods=salary1_periods,
        filing_status=filing_status,
        total_ca_tax=total_ca * salary1_pct,
        num_dependents=facts.children_under_17 + facts.other_dependents,
    )
    de4_guidance.append(de4_1)

    if dual_income and salary2_annual > 0:
        # W-4 for Salary 2
        w4_2 = generate_w4_guidance(
            salary_num=2,
            annual_salary=salary2_annual,
            pay_periods=salary2_periods,
            filing_status=filing_status,
            dual_income=True,
            additional_income=additional_income * salary2_pct,
            extra_deduction=extra_deduction * salary2_pct,
            child_credit=child_credit * salary2_pct,
            total_federal_tax=total_federal * salary2_pct,
            se_tax=federal_result['se_tax']['total'] * salary2_pct
        )
        w4_guidance.append(w4_2)

        # DE 4 for Salary 2
        de4_2 = generate_de4_guidance(
            salary_num=2,
            annual_salary=salary2_annual,
            pay_periods=salary2_periods,
            filing_status=filing_status,
            total_ca_tax=total_ca * salary2_pct,
            num_dependents=0  # Dependents only claimed on one DE 4
        )
        de4_guidance.append(de4_2)

    # Quarterly payment guidance for 1099 income
    quarterly_guidance = None
    if additional_income > 0:
        quarterly_guidance = generate_quarterly_guidance(
            additional_income=additional_income,
            se_tax=federal_result['se_tax']['total'],
            tax_year=year
        )

    return {
        'w4_guidance': w4_guidance,
        'de4_guidance': de4_guidance,
        'quarterly_guidance': quarterly_guidance,
        'totals': {
            'federal_income_tax': round(federal_result['final_tax'], 2),
            'self_employment_tax': round(federal_result['se_tax']['total'], 2),
            'total_federal': round(total_federal, 2),
            'california_tax': round(total_ca, 2),
            'ca_sdi': round(total_sdi, 2),
            'grand_total': round(total_federal + total_ca + total_sdi, 2)
        }
    }


def generate_w4_guidance(salary_num, annual_salary, pay_periods, filing_status,
                         dual_income, additional_income, extra_deduction,
                         child_credit, total_federal_tax, se_tax):
    """
    Generate specific W-4 form guidance.
    """
    # Filing status mapping
    status_map = {
        'single': 'Single or Married filing separately',
        'married_jointly': 'Married filing jointly',
        'head_of_household': 'Head of household'
    }

    guidance = {
        'salary_num': salary_num,
        'annual_salary': round(annual_salary, 2),
        'step1': {
            'filing_status': status_map.get(filing_status, 'Single'),
            'explanation': 'Check the box matching your expected filing status for the tax year.'
        },
        'step2': {
            'check_box': dual_income and filing_status == 'married_jointly',
            'explanation': 'Check this box if you are married filing jointly AND both spouses work. This adjusts withholding to account for the higher combined tax bracket.'
        },
        'step3': {
            'amount': round(child_credit, 0),
            'explanation': f'Enter ${child_credit:,.0f} for dependents. This is your Child Tax Credit amount that reduces withholding.'
        },
        'step4a': {
            'amount': round(additional_income, 0),
            'explanation': f'Enter ${additional_income:,.0f} for other income (1099s, etc.). This ensures tax is withheld on income not subject to regular withholding.'
        },
        'step4b': {
            'amount': round(max(0, extra_deduction), 0),
            'explanation': f'Enter ${max(0, extra_deduction):,.0f} for deductions exceeding standard deduction. Only enter if you plan to itemize.'
        }
    }

    # Calculate extra withholding needed
    # Estimate standard withholding based on annual salary
    estimated_withholding = estimate_standard_withholding(annual_salary, filing_status, dual_income)

    # Tax owed allocated to this salary minus estimated withholding
    tax_shortfall = total_federal_tax - estimated_withholding

    # Include SE tax in extra withholding if applicable
    tax_shortfall += se_tax

    # Account for Step 3, 4a, 4b adjustments
    step_adjustments = (
        child_credit  # Reduces withholding
        - additional_income * 0.22  # Rough estimate of tax on additional income
        + extra_deduction * 0.22  # Tax savings from extra deductions
    )

    extra_withholding_per_pay = max(0, (tax_shortfall + step_adjustments) / pay_periods)

    guidance['step4c'] = {
        'amount': round(extra_withholding_per_pay, 0),
        'explanation': f'Enter ${extra_withholding_per_pay:,.0f} extra per paycheck to ensure sufficient withholding. This accounts for SE tax and any underwithholding from multiple income sources.'
    }

    return guidance


def generate_de4_guidance(salary_num, annual_salary, pay_periods, filing_status, total_ca_tax, num_dependents):
    """
    Generate specific California DE 4 form guidance.
    """
    # Filing status mapping for DE 4
    status_map = {
        'single': 'Single or Married (with two or more incomes)',
        'married_jointly': 'Married (one income)',
        'head_of_household': 'Head of Household'
    }

    # Calculate allowances
    # Base: 1 for yourself
    # Additional for dependents
    base_allowances = 1

    # For married with single income, can claim 2
    if filing_status == 'married_jointly':
        base_allowances = 2

    total_allowances = base_allowances + num_dependents

    # Estimate standard CA withholding
    estimated_ca_withholding = estimate_ca_withholding(annual_salary, total_allowances)

    # Calculate extra withholding needed
    withholding_shortfall = total_ca_tax - estimated_ca_withholding
    extra_per_pay = max(0, withholding_shortfall / pay_periods)

    return {
        'salary_num': salary_num,
        'annual_salary': round(annual_salary, 2),
        'filing_status': status_map.get(filing_status, 'Single'),
        'filing_status_explanation': 'Select the filing status that matches your tax return.',
        'allowances': total_allowances,
        'allowances_explanation': f'Claim {total_allowances} allowance(s): {base_allowances} for yourself' +
                                  (f' + {num_dependents} for dependents' if num_dependents > 0 else ''),
        'additional_withholding': round(extra_per_pay, 0),
        'additional_withholding_explanation': f'Enter ${extra_per_pay:,.0f} additional withholding per paycheck to ensure you meet your California tax obligation.'
    }


def estimate_standard_withholding(annual_salary, filing_status, dual_income):
    """
    Estimate standard federal withholding without any W-4 adjustments.
    This is a simplified approximation.
    """
    fed_profile = _get_registry().profile("federal", 2025, filing_status)
    std_deduction = _f(fed_profile.standard_deduction)

    # If dual income with married status, adjust
    if dual_income and filing_status == 'married_jointly':
        # Each job withholds as if it's the only income, so we approximate
        std_deduction = std_deduction / 2

    taxable = max(0, annual_salary - std_deduction)
    tax, _ = calculate_bracket_tax(taxable, fed_profile.brackets)

    return tax


def estimate_ca_withholding(annual_salary, allowances):
    """
    Estimate standard California withholding.
    """
    # Rough estimate: each allowance reduces taxable income by ~$4,800
    allowance_value = 4800
    taxable = max(0, annual_salary - (allowances * allowance_value))

    ca_profile = _get_registry().profile("CA", 2025, "single")
    tax, _ = calculate_bracket_tax(taxable, ca_profile.brackets)

    return tax


def generate_quarterly_guidance(additional_income, se_tax, tax_year):
    """
    Generate quarterly estimated tax payment guidance.
    """
    # Estimate federal tax on additional income (rough 22% marginal rate)
    federal_on_additional = additional_income * 0.22

    # Add SE tax
    total_quarterly_federal = federal_on_additional + se_tax

    # CA tax on additional income (rough 9.3% rate)
    ca_on_additional = additional_income * 0.093

    quarterly_federal = total_quarterly_federal / 4
    quarterly_ca = ca_on_additional / 4

    due_dates = _format_due_dates(tax_year)

    return {
        'has_1099_income': True,
        'annual_federal_estimate': round(total_quarterly_federal, 2),
        'annual_ca_estimate': round(ca_on_additional, 2),
        'quarterly_federal': round(quarterly_federal, 2),
        'quarterly_ca': round(quarterly_ca, 2),
        'due_dates': due_dates,
        'federal_form': 'Form 1040-ES',
        'ca_form': 'Form 540-ES',
        'explanation': 'If you have significant 1099 income, you may need to make quarterly estimated tax payments to avoid underpayment penalties. Pay quarterly if you expect to owe $1,000+ federal or $500+ California.'
    }


def calculate_all(facts):
    """
    Main entry point - calculate all taxes and generate guidance.
    Accepts a TaxFacts value object (or, for legacy callers, a dict that
    will be parsed into TaxFacts via build_facts).
    """
    if not isinstance(facts, _TaxFacts):
        from .tax_facts import build_facts
        facts = build_facts(facts, tax_tables=_get_registry(), state_engines=_get_engines())

    federal_result = calculate_federal_tax(facts)
    state_result = _compute_state_via_engine(facts, federal_result)
    withholding = calculate_withholding(facts, federal_result, state_result)

    return {
        'federal': federal_result,
        'california': state_result,  # backwards-compat key for existing UI/goldens
        'state': state_result,        # forward-looking key
        'withholding': withholding,
        'summary': {
            'tax_year': facts.tax_year,
            'filing_status': facts.filing_status,
            'gross_income': federal_result['gross_income'],
            'federal_tax': federal_result['final_tax'],
            'se_tax': federal_result['se_tax']['total'],
            'california_tax': state_result['final_tax'],
            'ca_sdi': state_result['sdi']['tax'],
            'total_tax': withholding['totals']['grand_total']
        }
    }


def _compute_state_via_engine(facts, federal_result):
    """Adapter: run the state engine for facts.state and reshape the result into
    the legacy CA-result dict shape so downstream consumers (calculate_withholding,
    UI templates, goldens) keep working unchanged."""
    year = facts.tax_year
    state_code = facts.state
    fed_itm = (
        _Decimal(str(federal_result['itemized_deduction']['total']))
        if federal_result['use_itemized']
        else _Decimal('0')
    )
    inp = facts.to_state_input(
        federal_agi=_Decimal(str(federal_result['agi'])),
        federal_taxable_income=_Decimal(str(federal_result['taxable_income'])),
        federal_itemized=fed_itm,
    )
    engine = _get_engines().get(state_code)
    result = engine.compute(inp)

    # Reshape to legacy CA-result dict
    sdi_value = float(result.addons.get('sdi', _Decimal('0')))
    mhst_value = float(result.surcharges.get('mhst', _Decimal('0')))
    exemption_value = float(result.credits.get('exemption', _Decimal('0')))
    dependent_value = float(result.credits.get('dependent', _Decimal('0')))
    return {
        'agi': float(result.starting_income),
        'standard_deduction': float(result.standard_deduction),
        'itemized_deduction': _itemized_for_legacy(facts, 'california', year),
        'use_itemized': result.use_itemized,
        'deduction_used': float(result.deduction_used),
        'taxable_income': float(result.taxable_income),
        'tax_before_credits': float(result.tax_before_credits),
        'bracket_breakdown': [],  # engine doesn't surface this yet
        'mental_health_tax': mhst_value,
        'exemption_credit': exemption_value,
        'dependent_credit': dependent_value,
        'total_credits': exemption_value + dependent_value,
        'final_tax': float(result.final_tax),
        'sdi': {
            'tax': sdi_value,
            'rate': float(_get_registry().extra(state_code, year, 'sdi')['rate']) * 100
                if state_code == 'CA' else 0,
            'wage_base': float(_get_registry().extra(state_code, year, 'sdi')['wage_base'])
                if state_code == 'CA' else 0,
            'taxable_wages': min(float(inp.wages_w2),
                float(_get_registry().extra(state_code, year, 'sdi')['wage_base']))
                if state_code == 'CA' else 0,
        },
    }
