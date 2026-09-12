from pathlib import Path


def test_storage_audit_is_non_destructive_and_daily_bounded():
    source = Path("storage_learning_audit_v1.py").read_text(encoding="utf-8")
    assert 'MIN_AUDIT_INTERVAL = timedelta(hours=20)' in source
    assert "pg_database_size(current_database())" in source
    assert "pg_total_relation_size(c.oid)" in source
    assert "pg_indexes_size(c.oid)" in source
    assert "pg_v2_storage_audit_runs" in source
    assert "pg_v2_storage_audit_relations" in source
    assert "DELETE FROM" not in source
    assert "TRUNCATE" not in source
    assert "VACUUM" not in source
    assert "DROP TABLE" not in source


def test_storage_audit_excludes_its_own_measurement_tables():
    source = Path("storage_learning_audit_v1.py").read_text(encoding="utf-8")
    # psycopg positional conversion requires literal SQL percent signs to be doubled.
    assert "c.relname NOT LIKE 'pg_v2_storage_audit_%%'" in source


def test_storage_audit_is_mounted_in_tradingdesk():
    panel = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    card = Path("tradingdesk_storage_audit_v1.py").read_text(encoding="utf-8")
    assert "render_tradingdesk_storage_audit_v1" in panel
    assert "capture_storage_audit_v1()" in card
    assert "Ingen data slettes" in card
