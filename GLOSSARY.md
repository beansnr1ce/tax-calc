# Glossary

Domain terms used in code, tests and issues. Use these words, not synonyms.

## Annual Tax Projection

Projection of a household's total tax liability for one tax year, broken out per authority (federal income tax, self-employment tax, state income tax, state SDI, Employee FICA). Separate from the withholding calculator. Served by `POST /project` and the `/projection` page; computed by `TaxPipeline.project` and returned as a `ProjectionResult`.

## Quick Projection

The minimal form of an Annual Tax Projection: tax year, filing status, state and one or two annual salaries. No pay frequency, deductions or YTD figures needed.

## YTD (year-to-date) figures

Amounts taken from a paystub covering the year so far: YTD gross wages, YTD federal/state withholding, YTD SDI. Plus household YTD estimated payments. They turn a projection into a mid-year projection.

## Projected Payments

Per authority, what the household is on track to pay for the year: YTD withheld + (current per-paycheck withholding x Paychecks Remaining) + YTD estimated payments.

## Paychecks Remaining

Number of paychecks left in the tax year for a salary. Defaults from the as-of date and pay frequency. A value the user supplies always wins.

## Refund / Balance Due

Per authority (federal, state, SDI): Projected Payments minus projected liability. Positive = refund, negative = balance due. Employee FICA is excluded. Self-employment tax counts toward the federal balance.

## Employee FICA

The employee's share of payroll taxes on W-2 wages: Social Security (capped at the wage base per salary) plus Medicare (all wages). FICA wages = gross wages less Section 125 deductions (health, dental, vision, FSA, HSA via payroll). 401(k), IRA and `other` pretax deductions do not reduce FICA wages.

## Section 125 deductions

Cafeteria-plan pretax deductions: health insurance, dental, vision, FSA, HSA. They reduce income-tax wages and payroll-tax wages (FICA, CA SDI). See `PretaxDeductions.section_125`.

## YTD Projection

A mid-year projection from paystub figures (year-to-date gross, withholding, SDI, estimated payments). Dated by an **as-of date** (today by default). Salary is assumed constant: **projected wages** = YTD gross + paychecks remaining × (annual salary ÷ periods per year), and these replace the plain annual salary in the projection. A salary with no YTD figures keeps its annual salary and counts no withholding.

## Paychecks Remaining

Paydays in the tax year strictly after the as-of date (YTD figures are assumed to include a paycheck dated that day). Weekly/biweekly: whole 7/14-day steps to Dec 31. Semimonthly: the 15th and last day of each month. Monthly: last day of each month. A user-entered value overrides the default.

## Projected Payments / Refund / Balance Due

Per authority (federal, state, SDI): YTD withheld + paychecks remaining × current per-paycheck withholding + YTD estimated payments. SDI has no per-paycheck input, so remaining SDI = SDI rate × remaining wages, up to what is left of the wage base after YTD gross. Payments − liability is a **refund** when positive and a **balance due** when negative. The federal liability is income tax + self-employment tax; Employee FICA is excluded (payroll withholds it exactly). When a balance is due and paychecks remain, the **extra withholding** suggestion is balance ÷ paychecks remaining (W-4 Step 4(c) federal, DE 4 state), placed on the salary with the most paychecks remaining.

## Additional Medicare Tax

An extra 0.9% Medicare tax on wages above a threshold set by filing status (single/HOH $200k, MFJ $250k). The projection applies it to combined household wages. Employers withhold it per employee once that employee's wages pass $200k, whatever the filing status, so paystubs can differ from the projection.

## Effective Rate

Total projected liability divided by total gross income. Gross income here is W-2 wages before pretax deductions plus all 1099 and other income.

## Marginal Rate

The statutory bracket rate on the next dollar of taxable income, for federal and state separately. At an exact bracket floor, the next dollar is taxed at the higher bracket. Phase-outs of credits and deductions are not included.

## Take-Home

Wage-based net pay: gross wages - pretax deductions - federal income tax - state income tax - SDI - Employee FICA. Given annually, and per paycheck when the pay frequency is known.

## SDI (State Disability Insurance)

California payroll tax. In a projection it is computed per employee: each salary's SDI wages (gross less Section 125 deductions) are capped at the wage base separately. The withholding calculator's legacy figure caps combined household wages once instead.
