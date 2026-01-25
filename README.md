# Tax Withholding Calculator

A Docker-based tax withholding calculator that helps determine the correct entries for **W-4** (Federal) and **DE 4** (California) forms. Calculates total estimated tax burden by taxing authority and provides specific, actionable guidance on what to enter on each form.

## Features

- **Tax Year Selection**: 2025 or 2026 tax tables and brackets
- **Filing Status**: Single, Married Filing Jointly, Head of Household
- **Dual Income Support**: Calculate withholding for households with 1 or 2 salaries
- **Flexible Pay Frequencies**: Weekly, bi-weekly, semi-monthly, or monthly
- **Additional Income**: 1099-G, 1099-NEC/MISC, 1099-INT/DIV, and other income
- **Self-Employment Tax**: Automatic 15.3% SE tax calculation on 1099-NEC income
- **Pre-tax Deductions**: 401(k), IRA, HSA, FSA, health/dental/vision insurance
- **Dependents**: Child Tax Credit ($2,000) and Other Dependent Credit ($500) with phase-out
- **Student Loan Interest**: Up to $2,500 deduction with phase-out calculation
- **Itemized Deductions**: Charitable, mortgage interest, SALT (with $10,000 cap), medical
- **Standard vs Itemized**: Automatically compares and uses the better option
- **California SDI**: State Disability Insurance calculation

## Quick Start (macOS)

### Prerequisites: Install Docker Desktop

If you don't have Docker installed:

1. Go to [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
2. Download and install Docker Desktop
3. Start Docker Desktop from Applications
4. Wait for Docker to fully start (whale icon in menu bar stops animating)

Verify installation:
```bash
docker --version
docker compose version
```

### Running the Calculator

1. **Clone or download this repository**:
   ```bash
   git clone <repository-url>
   cd tax-calc
   ```

2. **Build and start the container**:
   ```bash
   docker compose up --build
   ```

   First build takes ~30 seconds. Subsequent starts are instant.

3. **Access the calculator**:

   Open your browser to: **http://localhost:5001**

   > **Note**: We use port 5001 instead of 5000 to avoid conflicts with macOS AirPlay Receiver, which uses port 5000 by default.

4. **Stop the calculator**:

   Press `Ctrl+C` in the terminal, or run:
   ```bash
   docker compose down
   ```

### Running in Background

To run the calculator in the background:
```bash
docker compose up -d --build
```

To stop:
```bash
docker compose down
```

To view logs:
```bash
docker compose logs -f
```

## How It Works

### Tax Calculation Flow

1. **Gross Income**: Sum of all W-2 salaries and additional 1099 income
2. **Pre-tax Deductions**: Subtract 401(k), HSA, etc. from W-2 income
3. **AGI Adjustments**: Subtract 50% of SE tax, student loan interest
4. **Adjusted Gross Income (AGI)**: Income after above-the-line deductions
5. **Standard vs Itemized**: Compare and use the higher deduction
6. **Taxable Income**: AGI minus the chosen deduction
7. **Tax Calculation**: Apply progressive tax brackets
8. **Credits**: Subtract Child Tax Credit (with phase-out if applicable)
9. **Final Tax**: Your total federal/state tax liability

### W-4 Form Guidance

The calculator provides specific entries for each W-4 step:

| Step | What It Does | How We Calculate It |
|------|-------------|---------------------|
| **Step 1** | Filing status | Matches your selected filing status |
| **Step 2(c)** | Multiple jobs checkbox | Check if married filing jointly with two incomes |
| **Step 3** | Dependents | Child Tax Credit amount ($2,000 per child under 17, $500 others) |
| **Step 4(a)** | Other income | Your 1099 and other non-W-2 income |
| **Step 4(b)** | Deductions | Amount itemized exceeds standard deduction (if itemizing) |
| **Step 4(c)** | Extra withholding | Additional per-paycheck amount to cover SE tax or underwithholding |

### DE 4 Form Guidance

The calculator provides specific entries for the California DE 4:

| Field | What It Does | How We Calculate It |
|-------|-------------|---------------------|
| **Filing Status** | Withholding basis | Matches your filing status |
| **Allowances** | Reduces withholding | 1 for yourself + dependents (2 if married single income) |
| **Additional Withholding** | Extra per paycheck | Amount needed to meet CA tax obligation |

### Quarterly Estimated Payments

If you have 1099 income, the calculator provides:
- Estimated quarterly federal payment (Form 1040-ES)
- Estimated quarterly California payment (Form 540-ES)
- Due dates for the selected tax year

**Rule of thumb**: Make quarterly payments if you expect to owe $1,000+ federal or $500+ California.

### Dual Income Allocation

For households with two salaries, tax liability is allocated proportionally:
- If Salary 1 is 60% of total W-2 income, it gets 60% of tax responsibility
- Each salary gets its own W-4/DE 4 guidance
- Dependents are typically claimed on one W-4 only

## Tax Tables and Sources

### Federal Tax Brackets (2025)

| If Taxable Income Is Over | But Not Over | Tax Rate |
|--------------------------|--------------|----------|
| $0 | $11,925 (S) / $23,850 (MFJ) | 10% |
| $11,925 / $23,850 | $48,475 / $96,950 | 12% |
| $48,475 / $96,950 | $103,350 / $206,700 | 22% |
| $103,350 / $206,700 | $197,300 / $394,600 | 24% |
| $197,300 / $394,600 | $250,525 / $501,050 | 32% |
| $250,525 / $501,050 | $626,350 / $751,600 | 35% |
| $626,350 / $751,600 | - | 37% |

### California Tax Brackets (2025)

California has 9 brackets ranging from 1% to 12.3%, plus an additional 1% Mental Health Services Tax on income over $1,000,000.

### Standard Deductions (2025)

| Filing Status | Federal | California |
|--------------|---------|------------|
| Single | $15,000 | $5,540 |
| Married Filing Jointly | $30,000 | $11,080 |
| Head of Household | $22,500 | $11,080 |

### California SDI (2025)

- Rate: 1.2%
- Wage Base: $174,668
- Maximum SDI: $2,096.02

## Official Forms

- **IRS Form W-4**: [Employee's Withholding Certificate](https://www.irs.gov/forms-pubs/about-form-w-4)
- **California DE 4**: [Employee's Withholding Allowance Certificate](https://www.ftb.ca.gov/forms/misc/de4.html)
- **IRS Form 1040-ES**: [Estimated Tax for Individuals](https://www.irs.gov/forms-pubs/about-form-1040-es)
- **California Form 540-ES**: [Estimated Tax for Individuals](https://www.ftb.ca.gov/forms/2024/2024-540-es.pdf)

## Troubleshooting

### Docker Desktop Not Running

**Symptom**: `Cannot connect to the Docker daemon`

**Solution**: Start Docker Desktop from Applications and wait for it to fully initialize.

### Port 5001 Already in Use

**Symptom**: `Bind for 0.0.0.0:5001 failed: port is already allocated`

**Solution**:
1. Find what's using port 5001:
   ```bash
   lsof -i :5001
   ```
2. Either stop that process, or change the port in `docker-compose.yml`:
   ```yaml
   ports:
     - "5002:5000"  # Use port 5002 instead
   ```
   Then access the calculator at `http://localhost:5002`

> **Note**: We use port 5001 by default instead of 5000 to avoid conflicts with macOS AirPlay Receiver.

### macOS Firewall Prompt

**Symptom**: macOS asks if you want to allow incoming connections

**Solution**: Click "Allow" - this is needed for Docker networking.

### Container Keeps Restarting

**Symptom**: Container restarts in a loop

**Solution**: Check logs for errors:
```bash
docker compose logs
```

### Changes Not Reflected

**Symptom**: Code changes don't appear in the running app

**Solution**: Rebuild the container:
```bash
docker compose down
docker compose up --build
```

### Clear Everything and Start Fresh

```bash
docker compose down --volumes --rmi all
docker compose up --build
```

## Project Structure

```
tax-calc/
├── Dockerfile              # Container definition
├── docker-compose.yml      # Easy startup configuration
├── requirements.txt        # Python dependencies
├── README.md              # This file
└── app/
    ├── __init__.py        # Package marker
    ├── main.py            # Flask application
    ├── tax_calculator.py  # Core calculation engine
    ├── tax_tables.py      # Tax brackets and constants
    └── templates/
        └── index.html     # Web interface
```

## Limitations and Disclaimers

- **Estimates Only**: This calculator provides estimates based on simplified tax rules. Actual tax liability may differ.
- **Not Tax Advice**: This tool is for educational purposes. Consult a tax professional for specific advice.
- **Federal and California Only**: Does not calculate taxes for other states.
- **Limited Credits**: Only includes Child Tax Credit. Does not include Earned Income Credit, education credits, etc.
- **No AMT**: Does not calculate Alternative Minimum Tax.
- **Simplified SE Tax**: Does not account for all self-employment deductions.

## Contributing

Contributions are welcome! Areas for improvement:
- Additional tax credits (EITC, education credits)
- Support for other states
- AMT calculation
- More sophisticated SE tax handling
- Tax planning scenarios

## License

MIT License - feel free to use and modify for your needs.
