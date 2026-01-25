"""
Flask application for the Tax Withholding Calculator.
"""

from flask import Flask, render_template, request, jsonify
from .tax_calculator import calculate_all
from .tax_tables import IRA_LIMITS, _401K_LIMITS, HSA_LIMITS, PAY_FREQUENCIES

app = Flask(__name__)


@app.route('/')
def index():
    """Render the main calculator page."""
    return render_template('index.html',
                           ira_limits=IRA_LIMITS,
                           limits_401k=_401K_LIMITS,
                           hsa_limits=HSA_LIMITS,
                           pay_frequencies=list(PAY_FREQUENCIES.keys()))


@app.route('/calculate', methods=['POST'])
def calculate():
    """
    Calculate taxes based on form input and return W-4/DE 4 guidance.
    """
    try:
        data = request.get_json()

        # Validate required fields
        required = ['tax_year', 'filing_status', 'salary1_gross', 'salary1_frequency']
        for field in required:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Convert numeric fields
        data['tax_year'] = int(data['tax_year'])
        data['salary1_input_type'] = data.get('salary1_input_type', 'per_period')
        data['salary1_gross'] = float(data.get('salary1_gross', 0) or 0)
        data['salary1_annual'] = float(data.get('salary1_annual', 0) or 0)
        data['dual_income'] = bool(data.get('dual_income', False))

        if data['dual_income']:
            data['salary2_input_type'] = data.get('salary2_input_type', 'per_period')
            data['salary2_gross'] = float(data.get('salary2_gross', 0) or 0)
            data['salary2_annual'] = float(data.get('salary2_annual', 0) or 0)
            data['salary2_frequency'] = data.get('salary2_frequency', 'biweekly')
        else:
            data['salary2_input_type'] = 'per_period'
            data['salary2_gross'] = 0
            data['salary2_annual'] = 0

        # 1099 income
        data['income_1099g'] = float(data.get('income_1099g', 0) or 0)
        data['income_1099nec'] = float(data.get('income_1099nec', 0) or 0)
        data['income_1099int_div'] = float(data.get('income_1099int_div', 0) or 0)
        data['other_income'] = float(data.get('other_income', 0) or 0)

        # Pre-tax deductions for salary 1
        pretax_1 = data.get('pretax_deductions_1', {})
        data['pretax_deductions_1'] = {
            'input_type': pretax_1.get('input_type', 'per_period'),
            '_401k': float(pretax_1.get('_401k', 0) or 0),
            'ira': float(pretax_1.get('ira', 0) or 0),
            'health_insurance': float(pretax_1.get('health_insurance', 0) or 0),
            'hsa': float(pretax_1.get('hsa', 0) or 0),
            'fsa': float(pretax_1.get('fsa', 0) or 0),
            'dental': float(pretax_1.get('dental', 0) or 0),
            'vision': float(pretax_1.get('vision', 0) or 0),
            'other': float(pretax_1.get('other', 0) or 0)
        }

        # Pre-tax deductions for salary 2
        if data['dual_income']:
            pretax_2 = data.get('pretax_deductions_2', {})
            data['pretax_deductions_2'] = {
                'input_type': pretax_2.get('input_type', 'per_period'),
                '_401k': float(pretax_2.get('_401k', 0) or 0),
                'ira': float(pretax_2.get('ira', 0) or 0),
                'health_insurance': float(pretax_2.get('health_insurance', 0) or 0),
                'hsa': float(pretax_2.get('hsa', 0) or 0),
                'fsa': float(pretax_2.get('fsa', 0) or 0),
                'dental': float(pretax_2.get('dental', 0) or 0),
                'vision': float(pretax_2.get('vision', 0) or 0),
                'other': float(pretax_2.get('other', 0) or 0)
            }

        # Dependents
        data['children_under_17'] = int(data.get('children_under_17', 0) or 0)
        data['other_dependents'] = int(data.get('other_dependents', 0) or 0)

        # Student loan interest
        data['student_loan_interest'] = float(data.get('student_loan_interest', 0) or 0)

        # Itemized deductions
        itemized = data.get('itemized_deductions', {})
        data['itemized_deductions'] = {
            'charitable': float(itemized.get('charitable', 0) or 0),
            'mortgage_interest': float(itemized.get('mortgage_interest', 0) or 0),
            'salt': float(itemized.get('salt', 0) or 0),
            'medical': float(itemized.get('medical', 0) or 0),
            'other': float(itemized.get('other', 0) or 0)
        }

        # Calculate everything
        result = calculate_all(data)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
