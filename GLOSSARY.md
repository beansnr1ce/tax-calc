# Glossary

Domain terms used in code, tests and issues. Use these words, not synonyms.

## Annual Tax Projection

Projection of a household's total tax liability for one tax year, broken out per authority (federal income tax, self-employment tax, state income tax, state SDI, Employee FICA). Separate from the withholding calculator. Served by `POST /project` and the `/projection` page; computed by `TaxPipeline.project` and returned as a `ProjectionResult`.

## Quick Projection

The minimal form of an Annual Tax Projection: tax year, filing status, state and one or two annual salaries. No pay frequency, deductions or YTD figures needed.

## YTD Projection

A mid-year projection from paystub **YTD (year-to-date) figures**: per salary, YTD gross wages, YTD federal/state withholding and YTD SDI, plus household YTD estimated payments. Dated by an **as-of date** (today by default). Once any YTD figure is entered, every salary needs a pay frequency and YTD gross. Salary is assumed constant: **projected wages** = YTD gross + Paychecks Remaining × (annual salary ÷ periods per year), and these replace the plain annual salary in the projection.

## Paychecks Remaining

Number of paychecks left in the tax year for a salary. Defaults to the paydays strictly after the as-of date (YTD figures are assumed to include a paycheck dated that day). Weekly/biweekly: whole 7/14-day steps to Dec 31. Semimonthly: the 15th and last day of each month. Monthly: last day of each month. A user-entered value always wins.

## Projected Payments

Per authority (federal, state, SDI), what the household is on track to pay for the year: YTD withheld + Paychecks Remaining × current per-paycheck withholding + YTD estimated payments. SDI has no per-paycheck input, so remaining SDI = SDI rate × remaining payroll wages (gross less Section 125 deductions, the same basis as the SDI liability).

## Refund / Balance Due

Per authority: Projected Payments − projected liability (`AuthorityBalance.refund_or_balance_due`). A **refund** when positive, a **balance due** when negative. The federal liability is income tax + self-employment tax; Employee FICA is excluded (payroll withholds it exactly).

## Extra Withholding Suggestion

When a balance is due and paychecks remain: balance due ÷ Paychecks Remaining, per paycheck (W-4 Step 4(c) federal, DE 4 state). It is placed on the salary with the most paychecks remaining (ties go to salary 1), so the extra is spread as thinly as possible.

## Employee FICA

The employee's share of payroll taxes on W-2 wages: Social Security (capped at the wage base per salary) plus Medicare (all wages). FICA wages = gross wages less Section 125 deductions (health, dental, vision, FSA, HSA via payroll). 401(k), IRA and `other` pretax deductions do not reduce FICA wages.

## Section 125 deductions

Cafeteria-plan pretax deductions: health insurance, dental, vision, FSA, HSA. They reduce income-tax wages and payroll-tax wages (FICA, CA SDI). See `PretaxDeductions.section_125`.

## Additional Medicare Tax

An extra 0.9% Medicare tax on wages above a threshold set by filing status (single/HOH $200k, MFJ $250k). The projection applies it to combined household wages. Employers withhold it per employee once that employee's wages pass $200k, whatever the filing status, so paystubs can differ from the projection.

## Effective Rate

Total projected liability divided by total gross income. Gross income here is W-2 wages before pretax deductions plus all 1099 and other income.

## Marginal Rate

The statutory bracket rate on the next dollar of taxable income, for federal and state separately. At an exact bracket floor, the next dollar is taxed at the higher bracket. Phase-outs of credits and deductions are not included.

## Take-Home

Wage-based net pay: gross wages - pretax deductions - federal income tax - state income tax - SDI - Employee FICA. Given annually, and per paycheck when the household pay frequency is known: the frequency shared by every salary that has one. A salary with no frequency does not block it; two salaries with different frequencies do (no per-paycheck figure).

## SDI (State Disability Insurance)

California payroll tax on each employee's SDI wages (gross less Section 125 deductions in a projection). Since 2024 (SB 951) there is no wage ceiling, so the tax tables have no `wage_base`. When a table does have one, a projection caps each salary separately, while the withholding calculator's legacy figure caps combined household wages once.
