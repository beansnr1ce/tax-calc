"""Pay schedule → annual periods multiplier. Not tax data; pure normalization."""

PAY_FREQUENCIES = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
    "quarterly": 4,
    "annually": 1,
}
