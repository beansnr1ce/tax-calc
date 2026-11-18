# 1. Annual Tax Projection: typed result, paystub-based withholding, household Additional Medicare

Status: accepted (2026-11, issue #17 / #18)

## Context

The withholding calculator (`TaxPipeline.calculate_all`) returns a large float-based legacy dict built around per-paycheck W-4 / DE 4 guidance. The Annual Tax Projection (see GLOSSARY.md) answers a different question: how much will the household owe for the year, and is it on track to pay that? We had to decide how the projection relates to the legacy path, how it estimates the rest of the year's withholding, and at what level it applies the Additional Medicare Tax.

## Decisions

### Separate typed projection result

`TaxPipeline.project(raw_inputs)` returns a `ProjectionResult` (`app/projection/`): frozen dataclasses with unrounded Decimal amounts. It reuses tax facts normalization, `FederalEngine` and the state engine registry. It does not go through `calculate_all` and has no legacy-dict shim. Rounding and JSON shape are handled by the `POST /project` route.

- New liability lines go on `Liabilities` as fields. `Liabilities.total` sums every field.
- New sections (marginal rates, take-home, YTD) are added as defaulted fields on `ProjectionResult`.
- Annual salary input is a facts-builder concern: `salaryN_annual` is an alternative to `salaryN_gross`. Pay frequency is optional only when `build_facts(..., require_frequency=False)`, which the projection uses. The withholding calculator still requires a frequency, because its math is per paycheck.
- Per-paycheck pretax deductions with no pay frequency are rejected with the code `frequency_required`.
- The projection requires `state`. The legacy builder defaults it to CA.
- Projection validation errors return HTTP 400. `/calculate` keeps 422. Both use the same body shape.

Why: this follows the typed `FederalResult` boundary (#8). It avoids extending a float dict that is pinned by golden tests, and the two features can change independently.

### Paystub-based remaining withholding (not Pub 15-T)

Mid-year projected payments use the user's current per-paycheck withholding from a paystub x Paychecks Remaining. We do not estimate withholding from W-4 settings with IRS Pub 15-T tables.

Why: paystub figures are what the user actually pays. Pub 15-T would mean modeling every W-4 field and employer quirk for little gain.

### Household-level Additional Medicare

The Additional Medicare Tax applies to combined household wages against the filing-status threshold, as on Form 8959. Employer withholding (per employee above $200k) is explained in the UI but not reconciled.

### Payroll-tax wages (FICA, SDI)

- Section 125 deductions (health insurance, dental, vision, FSA, HSA) reduce FICA and CA SDI wages.
- 401(k), IRA and `other` do not. Treating `other` this way is conservative: it may overstate payroll tax slightly.
- Projection SDI is computed per employee in the projection layer: each salary is capped at the wage base separately. `CaliforniaEngine`'s household-combined SDI addon is left alone, so withholding-calculator and golden outputs do not change.
- Treating HSA payroll contributions as reducing CA SDI wages follows the cafeteria-plan treatment and is a simplification.

## Consequences

- Two code paths compute overlapping numbers, such as SDI, slightly differently. The projection is the more accurate of the two.
- Self-employment tax is not coordinated with W-2 wages for the Social Security wage base, and Additional Medicare is not applied to SE income. Both are known gaps, inherited from `FederalEngine`.
