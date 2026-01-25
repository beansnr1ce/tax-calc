"""
Core tax calculation engine for federal and California taxes.
Provides W-4 and DE 4 form guidance.
"""

from .tax_tables import (
    get_federal_brackets, get_ca_brackets,
    FEDERAL_STANDARD_DEDUCTION, CA_STANDARD_DEDUCTION,
    CA_EXEMPTION_CREDIT, CA_SDI, CA_MENTAL_HEALTH_THRESHOLD,
    SELF_EMPLOYMENT_TAX_RATE, SELF_EMPLOYMENT_SS_WAGE_BASE,
    CHILD_TAX_CREDIT, STUDENT_LOAN_INTEREST,
    SALT_CAP, PAY_FREQUENCIES, QUARTERLY_DUE_DATES,
    IRA_LIMITS, _401K_LIMITS, HSA_LIMITS
)


def calculate_bracket_tax(taxable_income, brackets):
    """
    Calculate tax using progressive brackets.
    Returns (total_tax, bracket_breakdown).
    """
    tax = 0
    prev_limit = 0
    breakdown = []

    for limit, rate in brackets:
        if taxable_income <= prev_limit:
            break
        taxable_in_bracket = min(taxable_income, limit) - prev_limit
        if taxable_in_bracket > 0:
            tax_in_bracket = taxable_in_bracket * rate
            tax += tax_in_bracket
            breakdown.append({
                'bracket_start': prev_limit,
                'bracket_end': limit if limit != float('inf') else 'unlimited',
                'rate': rate * 100,
                'taxable_amount': taxable_in_bracket,
                'tax': tax_in_bracket
            })
        prev_limit = limit

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
    ss_wage_base = SELF_EMPLOYMENT_SS_WAGE_BASE.get(year, 176100)

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


def calculate_child_tax_credit(children_under_17, other_dependents, agi, filing_status):
    """
    Calculate Child Tax Credit with phase-out.
    $2,000 per child under 17, $500 per other dependent.
    Phase-out: $50 reduction per $1,000 over threshold.
    """
    base_credit = (children_under_17 * CHILD_TAX_CREDIT['under_17'] +
                   other_dependents * CHILD_TAX_CREDIT['other_dependent'])

    if base_credit == 0:
        return {'total': 0, 'phased_out': 0, 'explanation': 'No dependents claimed'}

    threshold = CHILD_TAX_CREDIT['phase_out_start'].get(filing_status, 200000)

    if agi <= threshold:
        return {
            'total': base_credit,
            'phased_out': 0,
            'explanation': f'Full credit: AGI ${agi:,.0f} is below phase-out threshold of ${threshold:,}'
        }

    # Calculate phase-out
    excess = agi - threshold
    phase_out_amount = (excess // 1000) * CHILD_TAX_CREDIT['phase_out_rate']
    final_credit = max(0, base_credit - phase_out_amount)

    return {
        'total': final_credit,
        'phased_out': min(base_credit, phase_out_amount),
        'explanation': f'Credit reduced by ${phase_out_amount:,.0f} due to AGI ${agi:,.0f} exceeding ${threshold:,} threshold'
    }


def calculate_student_loan_deduction(interest_paid, agi, filing_status, year):
    """
    Calculate student loan interest deduction with phase-out.
    Max $2,500, phases out at higher incomes.
    """
    if interest_paid <= 0:
        return {'deduction': 0, 'explanation': 'No student loan interest entered'}

    max_deduction = min(interest_paid, STUDENT_LOAN_INTEREST['max_deduction'])
    phase_out_start = STUDENT_LOAN_INTEREST['phase_out_start'][year].get(filing_status, 80000)
    phase_out_range = STUDENT_LOAN_INTEREST['phase_out_range'].get(filing_status, 15000)

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


def calculate_ca_sdi(wages, year):
    """
    Calculate California State Disability Insurance.
    """
    sdi_info = CA_SDI.get(year, CA_SDI[2025])
    taxable_wages = min(wages, sdi_info['wage_base'])
    sdi_tax = taxable_wages * sdi_info['rate']

    return {
        'tax': round(sdi_tax, 2),
        'rate': sdi_info['rate'] * 100,
        'wage_base': sdi_info['wage_base'],
        'taxable_wages': taxable_wages
    }


def calculate_federal_tax(data):
    """
    Calculate complete federal tax liability.
    """
    year = data['tax_year']
    filing_status = data['filing_status']

    # Calculate gross income from all sources
    salary1_annual = data['salary1_gross'] * PAY_FREQUENCIES.get(data['salary1_frequency'], 26)
    salary2_annual = 0
    if data.get('dual_income'):
        salary2_annual = data.get('salary2_gross', 0) * PAY_FREQUENCIES.get(data.get('salary2_frequency', 'biweekly'), 26)

    w2_income = salary1_annual + salary2_annual

    # Additional income (1099s)
    income_1099g = data.get('income_1099g', 0)
    income_1099nec = data.get('income_1099nec', 0)
    income_1099int_div = data.get('income_1099int_div', 0)
    other_income = data.get('other_income', 0)

    total_additional_income = income_1099g + income_1099nec + income_1099int_div + other_income

    # Self-employment tax calculation
    se_tax = calculate_self_employment_tax(income_1099nec, year)

    # Calculate pre-tax deductions (401k, HSA, etc.)
    pretax_salary1 = calculate_pretax_deductions(data.get('pretax_deductions_1', {}), data['salary1_frequency'])
    pretax_salary2 = 0
    if data.get('dual_income'):
        pretax_salary2 = calculate_pretax_deductions(data.get('pretax_deductions_2', {}), data.get('salary2_frequency', 'biweekly'))

    total_pretax = pretax_salary1 + pretax_salary2

    # Adjusted Gross Income (AGI)
    gross_income = w2_income + total_additional_income
    agi_deductions = total_pretax + se_tax['deduction']

    # Student loan interest deduction
    student_loan = calculate_student_loan_deduction(
        data.get('student_loan_interest', 0),
        gross_income - agi_deductions,
        filing_status,
        year
    )
    agi_deductions += student_loan['deduction']

    agi = gross_income - agi_deductions

    # Determine deduction (standard vs itemized)
    standard_deduction = FEDERAL_STANDARD_DEDUCTION[year][filing_status]
    itemized = calculate_itemized_deductions(data.get('itemized_deductions', {}), 'federal')

    use_itemized = itemized['total'] > standard_deduction
    deduction_amount = itemized['total'] if use_itemized else standard_deduction

    # Taxable income
    taxable_income = max(0, agi - deduction_amount)

    # Calculate tax using brackets
    brackets = get_federal_brackets(year, filing_status)
    tax, bracket_breakdown = calculate_bracket_tax(taxable_income, brackets)

    # Child Tax Credit
    child_credit = calculate_child_tax_credit(
        data.get('children_under_17', 0),
        data.get('other_dependents', 0),
        agi,
        filing_status
    )

    # Final tax after credits
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


def calculate_california_tax(data, federal_result):
    """
    Calculate California state tax liability.
    """
    year = data['tax_year']
    filing_status = data['filing_status']

    # California uses same income as federal with some adjustments
    agi = federal_result['agi']

    # California standard deduction
    standard_deduction = CA_STANDARD_DEDUCTION[year][filing_status]

    # California itemized (different rules - no SALT cap for state)
    itemized = calculate_itemized_deductions(data.get('itemized_deductions', {}), 'california')

    use_itemized = itemized['total'] > standard_deduction
    deduction_amount = itemized['total'] if use_itemized else standard_deduction

    # Taxable income
    taxable_income = max(0, agi - deduction_amount)

    # Calculate tax using CA brackets
    brackets = get_ca_brackets(year, filing_status)
    tax, bracket_breakdown = calculate_bracket_tax(taxable_income, brackets)

    # Mental Health Services Tax (additional 1% on income over $1M)
    mental_health_tax = 0
    if taxable_income > CA_MENTAL_HEALTH_THRESHOLD:
        mental_health_tax = (taxable_income - CA_MENTAL_HEALTH_THRESHOLD) * 0.01

    # California Exemption Credit
    exemption_credit = CA_EXEMPTION_CREDIT[year][filing_status]

    # Dependent exemption credits
    num_dependents = data.get('children_under_17', 0) + data.get('other_dependents', 0)
    dependent_credit = num_dependents * 446  # 2025 value

    total_credits = exemption_credit + dependent_credit

    # Final tax
    final_tax = max(0, tax + mental_health_tax - total_credits)

    # SDI calculation
    w2_income = federal_result['w2_income']
    sdi = calculate_ca_sdi(w2_income, year)

    return {
        'agi': round(agi, 2),
        'standard_deduction': standard_deduction,
        'itemized_deduction': itemized,
        'use_itemized': use_itemized,
        'deduction_used': round(deduction_amount, 2),
        'taxable_income': round(taxable_income, 2),
        'tax_before_credits': round(tax, 2),
        'bracket_breakdown': bracket_breakdown,
        'mental_health_tax': round(mental_health_tax, 2),
        'exemption_credit': exemption_credit,
        'dependent_credit': dependent_credit,
        'total_credits': total_credits,
        'final_tax': round(final_tax, 2),
        'sdi': sdi
    }


def calculate_pretax_deductions(deductions, frequency):
    """
    Calculate annual pre-tax deductions from pay period or annual amounts.
    """
    if not deductions:
        return 0

    periods = PAY_FREQUENCIES.get(frequency, 26)
    is_annual = deductions.get('input_type') == 'annual'

    total = 0
    for key in ['_401k', 'ira', 'health_insurance', 'hsa', 'fsa', 'dental', 'vision', 'other']:
        amount = deductions.get(key, 0) or 0
        if is_annual:
            total += amount
        else:
            total += amount * periods

    return total


def calculate_itemized_deductions(deductions, tax_type):
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
        # Federal SALT cap of $10,000
        salt_allowed = min(salt, SALT_CAP)
        breakdown['salt'] = salt_allowed
        breakdown['salt_capped'] = salt > SALT_CAP
        breakdown['salt_original'] = salt
    else:
        # California has no SALT cap (but doesn't allow SALT deduction for CA taxes paid)
        # CA allows property tax but not state income tax
        property_tax_estimate = salt * 0.5  # Rough estimate, assuming half is property tax
        breakdown['salt'] = property_tax_estimate

    total = sum(breakdown.get(k, 0) for k in ['charitable', 'mortgage_interest', 'salt', 'medical', 'other'])

    return {'total': round(total, 2), 'breakdown': breakdown}


def calculate_withholding(data, federal_result, ca_result):
    """
    Calculate current withholding and provide W-4/DE 4 guidance.
    """
    year = data['tax_year']
    filing_status = data['filing_status']
    dual_income = data.get('dual_income', False)

    salary1_annual = federal_result['salary1_annual']
    salary1_periods = PAY_FREQUENCIES.get(data['salary1_frequency'], 26)

    salary2_annual = federal_result['salary2_annual']
    salary2_periods = PAY_FREQUENCIES.get(data.get('salary2_frequency', 'biweekly'), 26) if dual_income else 0

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
        num_dependents=data.get('children_under_17', 0) + data.get('other_dependents', 0)
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
    # Use 2025 standard deduction
    std_deduction = FEDERAL_STANDARD_DEDUCTION[2025][filing_status]

    # If dual income with married status, adjust
    if dual_income and filing_status == 'married_jointly':
        # Each job withholds as if it's the only income, so we approximate
        std_deduction = std_deduction / 2

    taxable = max(0, annual_salary - std_deduction)
    brackets = get_federal_brackets(2025, filing_status)
    tax, _ = calculate_bracket_tax(taxable, brackets)

    return tax


def estimate_ca_withholding(annual_salary, allowances):
    """
    Estimate standard California withholding.
    """
    # Rough estimate: each allowance reduces taxable income by ~$4,800
    allowance_value = 4800
    taxable = max(0, annual_salary - (allowances * allowance_value))

    brackets = get_ca_brackets(2025, 'single')
    tax, _ = calculate_bracket_tax(taxable, brackets)

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

    due_dates = QUARTERLY_DUE_DATES.get(tax_year, QUARTERLY_DUE_DATES[2025])

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


def calculate_all(data):
    """
    Main entry point - calculate all taxes and generate guidance.
    """
    federal_result = calculate_federal_tax(data)
    ca_result = calculate_california_tax(data, federal_result)
    withholding = calculate_withholding(data, federal_result, ca_result)

    return {
        'federal': federal_result,
        'california': ca_result,
        'withholding': withholding,
        'summary': {
            'tax_year': data['tax_year'],
            'filing_status': data['filing_status'],
            'gross_income': federal_result['gross_income'],
            'federal_tax': federal_result['final_tax'],
            'se_tax': federal_result['se_tax']['total'],
            'california_tax': ca_result['final_tax'],
            'ca_sdi': ca_result['sdi']['tax'],
            'total_tax': withholding['totals']['grand_total']
        }
    }
