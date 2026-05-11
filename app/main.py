"""
Flask application for the Tax Withholding Calculator.
"""

import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from .state_tax import StateEngineRegistry
from .state_tax.states import register_overrides
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
        return jsonify({
            "error": "validation_failed",
            "fields": [
                {"field": err.field, "code": err.code, "message": err.message,
                 "detail": {k: str(v) for k, v in err.detail.items()}}
                for err in e.errors
            ],
        }), 422

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
