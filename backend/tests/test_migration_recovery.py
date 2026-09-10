from pathlib import Path


VERSIONS = Path(__file__).parents[1] / "alembic/versions"


def test_foundation_migration_resolves_renamed_time_off_model_without_key_error():
    source = (VERSIONS / "q5r6s7t8u9v0_enterprise_pm_psa_foundation.py").read_text()

    assert '"time_off": "leave_requests"' in source
    assert "Base.metadata.tables.get" in source
    assert "_physical_table_name" in source
    assert "Preserve a legacy physical table" in source
    assert 'Base.metadata.tables[name].create' not in source


def test_calendar_event_links_are_created_after_calendar_entries_exist():
    foundation = (VERSIONS / "q5r6s7t8u9v0_enterprise_pm_psa_foundation.py").read_text()
    erp = (VERSIONS / "v0w1x2y3z4a5_erp_reliability_workspace.py").read_text()

    assert '"calendar_event_links"' not in foundation.split("def downgrade", 1)[0]
    assert 'Base.metadata.tables["calendar_event_links"].create' in erp
    assert erp.index('op.create_table(\n        "calendar_entries"') < erp.index(
        'Base.metadata.tables["calendar_event_links"].create'
    )
