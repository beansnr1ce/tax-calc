"""
Secondary seam: the HTTP surface for Annual Tax Projection.
Shape and status codes only; tax math is covered in test_projection.py.
"""

import pytest

from app.main import app


@pytest.fixture
def client():
    return app.test_client()


def _payload(**overrides):
    payload = {
        "tax_year": 2025,
        "filing_status": "single",
        "state": "CA",
        "salary1_annual": 78000,
    }
    payload.update(overrides)
    return payload


def test_project_returns_200_with_projection_shape(client):
    resp = client.post("/project", json=_payload())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tax_year"] == 2025
    assert body["filing_status"] == "single"
    assert body["state"] == "CA"
    assert set(body["liabilities"]) >= {
        "federal_income_tax",
        "self_employment_tax",
        "state_income_tax",
        "state_sdi",
    }
    for key in ("gross_income", "total_liability", "effective_rate"):
        assert key in body
    # Decimals are serialized as strings rounded at the route
    assert body["liabilities"]["federal_income_tax"] == "8774.00"


def test_project_returns_400_with_field_errors_on_invalid_input(client):
    resp = client.post("/project", json={"filing_status": "single"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "validation_failed"
    fields = {f["field"] for f in body["fields"]}
    assert {"tax_year", "state", "salary1_gross"} <= fields
    assert all(f["message"] for f in body["fields"])


def test_projection_page_renders_form(client):
    resp = client.get("/projection")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for name in ("tax_year", "filing_status", "state", "salary1_annual", "salary2_annual"):
        assert f'name="{name}"' in html


def test_per_paycheck_pretax_without_frequency_returns_400(client):
    resp = client.post("/project", json=_payload(pretax_deductions_1={"_401k": 500}))
    assert resp.status_code == 400
    errors = resp.get_json()["fields"]
    assert any(
        f["field"] == "pretax_deductions_1.input_type" and f["code"] == "frequency_required"
        for f in errors
    )


def test_projection_page_has_collapsed_refinement_panels(client):
    html = client.get("/projection").get_data(as_text=True)
    for name in (
        "salary1_frequency",
        "salary2_frequency",
        "pretax1_input_type",
        "pretax1__401k",
        "pretax1_ira",
        "pretax1_hsa",
        "pretax1_fsa",
        "pretax1_health_insurance",
        "pretax1_dental",
        "pretax1_vision",
        "pretax1_other",
        "pretax2_input_type",
        "pretax2__401k",
        "income_1099g",
        "income_1099nec",
        "income_1099int_div",
        "other_income",
        "children_under_17",
        "other_dependents",
        "student_loan_interest",
        "itemized_charitable",
        "itemized_mortgage_interest",
        "itemized_salt",
        "itemized_medical",
        "itemized_other",
    ):
        assert f'name="{name}"' in html, name
    # Refinement panels are <details> elements, collapsed (no `open` attribute)
    assert html.count('<details class="refine"') >= 5
    assert '<details class="refine" open' not in html


def test_main_page_links_to_projection(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/projection"' in html
