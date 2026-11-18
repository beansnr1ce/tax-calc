"""
Flask application for the Tax Withholding Calculator.
"""

import os
from dataclasses import fields
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from .state_tax import NO_TAX_STATES, StateEngineRegistry
from .state_tax.states import register_overrides
from .projection import ProjectionResult
from .tax_calculator import TaxPipeline
from .tax_facts import FactsError, build_facts
from .tax_registry import FilesystemSource, TaxTableRegistry

app = Flask(__name__)

_DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "tax_tables"
_data_root = Path(os.environ.get("TAX_DATA_ROOT", _DEFAULT_DATA_ROOT))
_tax_tables = TaxTableRegistry(source=FilesystemSource(_data_root))
_state_engines = StateEngineRegistry(registry=_tax_tables)
register_overrides(_state_engines)
_pipeline = TaxPipeline(_tax_tables, _state_engines)
app.extensions["tax_tables"] = _tax_tables
app.extensions["state_engines"] = _state_engines
app.extensions["pipeline"] = _pipeline


@app.route('/')
def index():
    """Render the main calculator page."""
    return render_template('index.html')


def _validation_body(e: FactsError) -> dict:
    return {
        "error": "validation_failed",
        "fields": [
            {"field": err.field, "code": err.code, "message": err.message,
             "detail": {k: str(v) for k, v in err.detail.items()}}
            for err in e.errors
        ],
    }


_CENTS = Decimal("0.01")
_RATE_PLACES = Decimal("0.0001")


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def _rate(value: Decimal) -> str:
    return str(value.quantize(_RATE_PLACES, rounding=ROUND_HALF_UP))


def _serialize_projection(result: ProjectionResult) -> dict:
    """Decimal → rounded strings (money to cents, rates to 4 places)."""
    return {
        "tax_year": result.tax_year,
        "filing_status": result.filing_status,
        "state": result.state,
        "gross_income": _money(result.gross_income),
        "wage_income": _money(result.wage_income),
        "liabilities": {name: _money(v) for name, v in result.liabilities.items()},
        "fica": {f.name: _money(getattr(result.fica, f.name)) for f in fields(result.fica)},
        "total_liability": _money(result.total_liability),
        "effective_rate": _rate(result.effective_rate),
    }


@app.route('/projection')
def projection_page():
    """Render the Annual Tax Projection page."""
    tables = app.extensions["tax_tables"]
    states = sorted(set(NO_TAX_STATES) | (set(tables.jurisdictions()) - {"federal"}))
    return render_template(
        'projection.html', years=tables.years_for("federal"), states=states
    )


@app.route('/project', methods=['POST'])
def project():
    """Annual Tax Projection as JSON. 400 on invalid input."""
    pipeline: TaxPipeline = app.extensions["pipeline"]
    try:
        result = pipeline.project(request.get_json(silent=True) or {})
    except FactsError as e:
        return jsonify(_validation_body(e)), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(_serialize_projection(result))


@app.route('/calculate', methods=['POST'])
def calculate():
    """
    Calculate taxes based on form input and return W-4/DE 4 guidance.
    """
    pipeline: TaxPipeline = app.extensions["pipeline"]
    try:
        facts = build_facts(
            request.get_json() or {},
            tax_tables=pipeline.tax_tables,
            state_engines=pipeline.state_engines,
        )
    except FactsError as e:
        return jsonify(_validation_body(e)), 422

    try:
        return jsonify(pipeline.calculate_all(facts))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
