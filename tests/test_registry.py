from datetime import date
from decimal import Decimal

import pytest

from app.tax_registry import (
    Bracket,
    BracketTable,
    FilesystemSource,
    InMemorySource,
    MissingTaxYear,
    TaxTableRegistry,
    TaxTableSchemaError,
)


def test_registry_returns_profile_for_known_jurisdiction_year():
    source = InMemorySource(
        {
            ("federal", 2025): {
                "kind": "progressive",
                "filing_statuses": {
                    "single": {
                        "brackets": [
                            {"floor": "0", "rate": "0.10"},
                            {"floor": "11925", "rate": "0.12"},
                        ],
                        "standard_deduction": "15000",
                        "dependent_credit": "0",
                    }
                },
            }
        }
    )
    registry = TaxTableRegistry(source=source)

    profile = registry.profile("federal", 2025, "single")

    assert profile.jurisdiction == "federal"
    assert profile.year == 2025
    assert profile.filing_status == "single"
    assert profile.standard_deduction == Decimal("15000")


@pytest.fixture
def federal_2025_single_brackets() -> BracketTable:
    # Real 2025 federal single brackets (top trimmed for brevity)
    return BracketTable(
        brackets=(
            Bracket(floor=Decimal("0"), rate=Decimal("0.10")),
            Bracket(floor=Decimal("11925"), rate=Decimal("0.12")),
            Bracket(floor=Decimal("48475"), rate=Decimal("0.22")),
            Bracket(floor=Decimal("103350"), rate=Decimal("0.24")),
        )
    )


class TestBracketTableTaxOn:
    def test_zero_income_owes_zero(self, federal_2025_single_brackets):
        assert federal_2025_single_brackets.tax_on(Decimal("0")) == Decimal("0")

    def test_within_first_bracket(self, federal_2025_single_brackets):
        # 10% of 10000 = 1000
        assert federal_2025_single_brackets.tax_on(Decimal("10000")) == Decimal("1000")

    def test_at_first_bracket_ceiling(self, federal_2025_single_brackets):
        # 10% of 11925 = 1192.50
        assert federal_2025_single_brackets.tax_on(Decimal("11925")) == Decimal("1192.50")

    def test_spans_two_brackets(self, federal_2025_single_brackets):
        # 10% of 11925 + 12% of (20000 - 11925) = 1192.50 + 969.00 = 2161.50
        assert federal_2025_single_brackets.tax_on(Decimal("20000")) == Decimal("2161.50")

    def test_spans_multiple_brackets(self, federal_2025_single_brackets):
        # 10% * 11925 + 12% * (48475 - 11925) + 22% * (60000 - 48475)
        # = 1192.50 + 4386.00 + 2535.50 = 8114.00
        assert federal_2025_single_brackets.tax_on(Decimal("60000")) == Decimal("8114.00")

    def test_above_top_bracket(self, federal_2025_single_brackets):
        # 10% * 11925 + 12% * (48475 - 11925) + 22% * (103350 - 48475) + 24% * (200000 - 103350)
        # = 1192.50 + 4386.00 + 12072.50 + 23196.00 = 40847.00
        assert federal_2025_single_brackets.tax_on(Decimal("200000")) == Decimal("40847.00")


def _minimal_profile_data() -> dict:
    return {
        "kind": "progressive",
        "filing_statuses": {
            "single": {
                "brackets": [{"floor": "0", "rate": "0.10"}],
                "standard_deduction": "15000",
                "dependent_credit": "0",
            }
        },
    }


def test_missing_year_raises_with_available_years_for_jurisdiction():
    source = InMemorySource(
        {
            ("CA", 2025): _minimal_profile_data(),
            ("CA", 2026): _minimal_profile_data(),
            ("federal", 2025): _minimal_profile_data(),
        }
    )
    registry = TaxTableRegistry(source=source)

    with pytest.raises(MissingTaxYear) as exc_info:
        registry.profile("CA", 2027, "single")

    assert exc_info.value.jurisdiction == "CA"
    assert exc_info.value.year == 2027
    assert exc_info.value.available == [2025, 2026]


def test_missing_jurisdiction_raises_missing_tax_year_with_empty_available():
    source = InMemorySource({("federal", 2025): _minimal_profile_data()})
    registry = TaxTableRegistry(source=source)

    with pytest.raises(MissingTaxYear) as exc_info:
        registry.profile("CA", 2025, "single")

    assert exc_info.value.jurisdiction == "CA"
    assert exc_info.value.available == []


def test_extra_returns_jurisdiction_specific_value():
    source = InMemorySource(
        {
            ("CA", 2025): {
                **_minimal_profile_data(),
                "extras": {
                    "sdi": {"rate": "0.012", "wage_base": "174668"},
                    "exemption_credit": "144",
                },
            }
        }
    )
    registry = TaxTableRegistry(source=source)

    sdi = registry.extra("CA", 2025, "sdi")

    assert sdi == {"rate": Decimal("0.012"), "wage_base": Decimal("174668")}


def test_extra_raises_missing_tax_year_when_jurisdiction_year_absent():
    registry = TaxTableRegistry(source=InMemorySource({}))

    with pytest.raises(MissingTaxYear):
        registry.extra("CA", 2025, "sdi")


def test_extra_raises_key_error_when_extra_key_absent():
    source = InMemorySource({("CA", 2025): _minimal_profile_data()})
    registry = TaxTableRegistry(source=source)

    with pytest.raises(KeyError):
        registry.extra("CA", 2025, "sdi")


def test_federal_limit_returns_year_specific_decimal():
    source = InMemorySource(
        {
            ("federal", 2025): {
                **_minimal_profile_data(),
                "limits": {
                    "401k_employee_deferral": "23500",
                    "hsa_self_only": "4300",
                    "salt_cap": "10000",
                },
            }
        }
    )
    registry = TaxTableRegistry(source=source)

    assert registry.federal_limit(2025, "401k_employee_deferral") == Decimal("23500")
    assert registry.federal_limit(2025, "salt_cap") == Decimal("10000")


def test_federal_limit_missing_year_raises_missing_tax_year():
    registry = TaxTableRegistry(source=InMemorySource({}))

    with pytest.raises(MissingTaxYear):
        registry.federal_limit(2025, "401k_employee_deferral")


def test_federal_limit_missing_key_raises_key_error():
    source = InMemorySource(
        {
            ("federal", 2025): {
                **_minimal_profile_data(),
                "limits": {"401k_employee_deferral": "23500"},
            }
        }
    )
    registry = TaxTableRegistry(source=source)

    with pytest.raises(KeyError):
        registry.federal_limit(2025, "hsa_self_only")


def test_quarterly_due_dates_returns_year_specific_dates():
    source = InMemorySource(
        {
            ("federal", 2025): {
                **_minimal_profile_data(),
                "quarterly_due_dates": [
                    "2025-04-15",
                    "2025-06-16",
                    "2025-09-15",
                    "2026-01-15",
                ],
            }
        }
    )
    registry = TaxTableRegistry(source=source)

    assert registry.quarterly_due_dates(2025) == (
        date(2025, 4, 15),
        date(2025, 6, 16),
        date(2025, 9, 15),
        date(2026, 1, 15),
    )


def test_jurisdictions_returns_distinct_sorted_list():
    source = InMemorySource(
        {
            ("federal", 2025): _minimal_profile_data(),
            ("CA", 2025): _minimal_profile_data(),
            ("CA", 2026): _minimal_profile_data(),
            ("NY", 2026): _minimal_profile_data(),
        }
    )
    registry = TaxTableRegistry(source=source)

    assert registry.jurisdictions() == ["CA", "NY", "federal"]


def test_years_for_returns_sorted_years():
    source = InMemorySource(
        {
            ("CA", 2026): _minimal_profile_data(),
            ("CA", 2025): _minimal_profile_data(),
        }
    )
    registry = TaxTableRegistry(source=source)

    assert registry.years_for("CA") == [2025, 2026]


def test_years_for_unknown_jurisdiction_returns_empty():
    registry = TaxTableRegistry(source=InMemorySource({}))

    assert registry.years_for("CA") == []


def test_has_year_true_when_present():
    source = InMemorySource({("CA", 2025): _minimal_profile_data()})
    registry = TaxTableRegistry(source=source)

    assert registry.has_year("CA", 2025) is True


def test_has_year_false_when_absent():
    source = InMemorySource({("CA", 2025): _minimal_profile_data()})
    registry = TaxTableRegistry(source=source)

    assert registry.has_year("CA", 2026) is False
    assert registry.has_year("NY", 2025) is False


def test_with_fallback_returns_fallback_year_when_year_missing():
    source = InMemorySource(
        {
            ("CA", 2025): {
                "kind": "progressive",
                "filing_statuses": {
                    "single": {
                        "brackets": [{"floor": "0", "rate": "0.10"}],
                        "standard_deduction": "5540",
                        "dependent_credit": "446",
                    }
                },
            }
        }
    )
    registry = TaxTableRegistry(source=source)
    fallback_registry = registry.with_fallback(2025)

    profile = fallback_registry.profile("CA", 2027, "single")

    assert profile.year == 2027
    assert profile.standard_deduction == Decimal("5540")
    assert profile.dependent_credit == Decimal("446")


def test_with_fallback_does_not_mutate_parent_registry():
    source = InMemorySource({("CA", 2025): _minimal_profile_data()})
    registry = TaxTableRegistry(source=source)
    _ = registry.with_fallback(2025)

    with pytest.raises(MissingTaxYear):
        registry.profile("CA", 2027, "single")


def test_with_fallback_uses_real_year_when_present():
    source = InMemorySource(
        {
            ("CA", 2025): {
                "kind": "progressive",
                "filing_statuses": {
                    "single": {
                        "brackets": [{"floor": "0", "rate": "0.10"}],
                        "standard_deduction": "5540",
                        "dependent_credit": "0",
                    }
                },
            },
            ("CA", 2026): {
                "kind": "progressive",
                "filing_statuses": {
                    "single": {
                        "brackets": [{"floor": "0", "rate": "0.10"}],
                        "standard_deduction": "5650",
                        "dependent_credit": "0",
                    }
                },
            },
        }
    )
    registry = TaxTableRegistry(source=source)
    fallback_registry = registry.with_fallback(2025)

    profile = fallback_registry.profile("CA", 2026, "single")

    assert profile.standard_deduction == Decimal("5650")


def test_with_fallback_raises_when_fallback_year_also_missing():
    source = InMemorySource({("CA", 2025): _minimal_profile_data()})
    registry = TaxTableRegistry(source=source)
    fallback_registry = registry.with_fallback(2024)

    with pytest.raises(MissingTaxYear):
        fallback_registry.profile("CA", 2027, "single")


def test_eager_construction_raises_schema_error_with_location():
    bad_data = {
        "kind": "progressive",
        "filing_statuses": {
            "single": {
                "brackets": [{"floor": "0"}],  # missing "rate"
                "standard_deduction": "15000",
                "dependent_credit": "0",
            }
        },
    }
    source = InMemorySource({("federal", 2025): bad_data})

    with pytest.raises(TaxTableSchemaError) as exc_info:
        TaxTableRegistry(source=source)

    msg = str(exc_info.value)
    assert "federal" in msg
    assert "2025" in msg
    assert "rate" in msg


def test_schema_rejects_float_for_money():
    bad_data = {
        "kind": "progressive",
        "filing_statuses": {
            "single": {
                "brackets": [{"floor": 0, "rate": 0.10}],  # floats not strings
                "standard_deduction": "15000",
                "dependent_credit": "0",
            }
        },
    }
    source = InMemorySource({("federal", 2025): bad_data})

    with pytest.raises(TaxTableSchemaError):
        TaxTableRegistry(source=source)


def test_schema_rejects_unknown_filing_status():
    bad_data = {
        "kind": "progressive",
        "filing_statuses": {
            "wizard": {  # not a valid FilingStatus
                "brackets": [{"floor": "0", "rate": "0.10"}],
                "standard_deduction": "15000",
                "dependent_credit": "0",
            }
        },
    }
    source = InMemorySource({("CA", 2025): bad_data})

    with pytest.raises(TaxTableSchemaError) as exc_info:
        TaxTableRegistry(source=source)

    assert "wizard" in str(exc_info.value) or "filing_status" in str(exc_info.value)


def test_schema_rejects_missing_required_field():
    bad_data = {
        "kind": "progressive",
        "filing_statuses": {
            "single": {
                "brackets": [{"floor": "0", "rate": "0.10"}],
                # missing standard_deduction
                "dependent_credit": "0",
            }
        },
    }
    source = InMemorySource({("federal", 2025): bad_data})

    with pytest.raises(TaxTableSchemaError) as exc_info:
        TaxTableRegistry(source=source)

    assert "standard_deduction" in str(exc_info.value)


def test_schema_validation_can_be_disabled_with_eager_false():
    # When loading lazily, validation is deferred to the access point.
    bad_data = {
        "kind": "progressive",
        "filing_statuses": {
            "single": {
                "brackets": [{"floor": "0"}],  # missing rate
                "standard_deduction": "15000",
                "dependent_credit": "0",
            }
        },
    }
    source = InMemorySource({("federal", 2025): bad_data})

    # Should not raise at construction
    registry = TaxTableRegistry(source=source, eager=False)

    # But should raise when the bad data is actually accessed
    with pytest.raises(TaxTableSchemaError):
        registry.profile("federal", 2025, "single")


def test_filesystem_source_loads_yaml_files(tmp_path):
    fed_dir = tmp_path / "federal"
    fed_dir.mkdir()
    (fed_dir / "2025.yaml").write_text(
        """\
kind: progressive
filing_statuses:
  single:
    brackets:
      - {floor: "0", rate: "0.10"}
      - {floor: "11925", rate: "0.12"}
    standard_deduction: "15000"
    dependent_credit: "0"
"""
    )
    ca_dir = tmp_path / "CA"
    ca_dir.mkdir()
    (ca_dir / "2025.yaml").write_text(
        """\
kind: progressive
filing_statuses:
  single:
    brackets:
      - {floor: "0", rate: "0.01"}
    standard_deduction: "5540"
    dependent_credit: "446"
"""
    )

    source = FilesystemSource(tmp_path)
    registry = TaxTableRegistry(source=source)

    fed = registry.profile("federal", 2025, "single")
    assert fed.standard_deduction == Decimal("15000")
    assert fed.brackets.brackets[1].floor == Decimal("11925")

    ca = registry.profile("CA", 2025, "single")
    assert ca.dependent_credit == Decimal("446")

    assert sorted(source.list_available()) == sorted([("CA", 2025), ("federal", 2025)])


def test_filesystem_source_eager_validation_surfaces_file_path(tmp_path):
    fed_dir = tmp_path / "federal"
    fed_dir.mkdir()
    (fed_dir / "2025.yaml").write_text(
        """\
kind: progressive
filing_statuses:
  single:
    brackets:
      - {floor: "0"}
    standard_deduction: "15000"
    dependent_credit: "0"
"""
    )

    source = FilesystemSource(tmp_path)
    with pytest.raises(TaxTableSchemaError) as exc_info:
        TaxTableRegistry(source=source)

    msg = str(exc_info.value)
    assert "federal" in msg and "2025" in msg
