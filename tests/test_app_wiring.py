"""
Boundary tests for Flask app wiring of the TaxTableRegistry.
"""

from app.main import app
from app.tax_registry import TaxTableRegistry


def test_app_has_tax_tables_registry_in_extensions():
    registry = app.extensions["tax_tables"]
    assert isinstance(registry, TaxTableRegistry)


def test_app_registry_has_expected_jurisdictions_loaded():
    registry = app.extensions["tax_tables"]
    assert "federal" in registry.jurisdictions()
    assert "CA" in registry.jurisdictions()


def test_app_registry_has_expected_years_loaded():
    registry = app.extensions["tax_tables"]
    assert registry.years_for("federal") == [2025, 2026]
    assert registry.years_for("CA") == [2025, 2026]


def test_app_registry_can_resolve_a_real_profile():
    registry = app.extensions["tax_tables"]
    profile = registry.profile("federal", 2025, "single")
    # Smoke check — value pinned by characterization tests
    assert profile.standard_deduction > 0
