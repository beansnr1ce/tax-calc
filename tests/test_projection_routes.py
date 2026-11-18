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


def test_project_response_includes_employee_fica_lines(client):
    body = client.post("/project", json=_payload()).get_json()
    # 78,000 × 6.2% = 4,836; 78,000 × 1.45% = 1,131
    assert body["liabilities"]["social_security"] == "4836.00"
    assert body["liabilities"]["medicare"] == "1131.00"
    assert body["fica"]["additional_medicare"] == "0.00"
    assert body["fica"]["salary1_social_security"] == "4836.00"


def test_projection_page_explains_additional_medicare_withholding(client):
    html = client.get("/projection").get_data(as_text=True)
    assert "Additional Medicare" in html
    assert "$200,000 per employer" in html


# --- YTD / paystub projection (#22) -----------------------------------------


def test_ytd_without_pay_frequency_returns_400(client):
    resp = client.post("/project", json=_payload(ytd={"salary1": {"gross": 60000}}))
    assert resp.status_code == 400
    assert any(
        f["field"] == "salary1_frequency" and f["code"] == "frequency_required"
        for f in resp.get_json()["fields"]
    )


def test_project_response_includes_ytd_section(client):
    body = client.post(
        "/project",
        json=_payload(
            salary1_frequency="biweekly",
            ytd={
                "salary1": {
                    "gross": 60000,
                    "federal_withheld": 6000,
                    "federal_per_paycheck": 300,
                    "paychecks_remaining": 6,
                }
            },
        ),
    ).get_json()
    ytd = body["ytd"]
    assert ytd["salary1"]["paychecks_remaining"] == 6
    assert ytd["salary1"]["projected_wages"] == "78000.00"
    # 6,000 + 6 × 300 = 7,800 vs 8,774 → 974 due, 162.33 extra per paycheck
    assert ytd["federal"] == {
        "liability": "8774.00",
        "payments": "7800.00",
        "balance": "-974.00",
        "refund": "0.00",
        "balance_due": "974.00",
    }
    assert ytd["federal_extra_per_paycheck"] == "162.33"
    assert ytd["suggestion_salary"] == "salary1"
    assert ytd["salary2"] is None


def test_project_response_ytd_is_null_without_ytd_data(client):
    assert client.post("/project", json=_payload()).get_json()["ytd"] is None


def test_projection_page_has_collapsed_ytd_panel(client):
    html = client.get("/projection").get_data(as_text=True)
    assert '<details class="refine ytd"' in html
    assert '<details class="refine ytd" open' not in html
    for name in (
        "ytd1_gross",
        "ytd1_federal_withheld",
        "ytd1_state_withheld",
        "ytd1_sdi_withheld",
        "ytd1_federal_per_paycheck",
        "ytd1_state_per_paycheck",
        "ytd1_paychecks_remaining",
        "ytd2_gross",
        "ytd_federal_estimated_payments",
        "ytd_state_estimated_payments",
    ):
        assert f'name="{name}"' in html, name
    assert "W-4 Step 4(c)" in html
    assert "DE 4" in html
