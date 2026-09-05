from __future__ import annotations

from types import SimpleNamespace

from database import DatabaseConnection, _split_postgres_script


def test_postgres_script_splitter_ignores_semicolon_in_line_comment():
    script = """
    CREATE TABLE one (id INTEGER);
    -- exact frozen object; this table is the analysis-friendly projection of it.
    CREATE TABLE two (id INTEGER);
    """

    statements = _split_postgres_script(script)

    assert len(statements) == 2
    assert "CREATE TABLE one" in statements[0]
    assert "exact frozen object; this table" in statements[1]
    assert "CREATE TABLE two" in statements[1]


def test_postgres_script_splitter_preserves_quoted_and_dollar_semicolons():
    script = """
    INSERT INTO notes(value) VALUES ('alpha;beta');
    CREATE FUNCTION demo() RETURNS void AS $$
    BEGIN
        PERFORM 'inside;body';
    END;
    $$ LANGUAGE plpgsql;
    /* block; comment */
    SELECT "semi;column" FROM demo_table;
    """

    statements = _split_postgres_script(script)

    assert len(statements) == 3
    assert "'alpha;beta'" in statements[0]
    assert "PERFORM 'inside;body';" in statements[1]
    assert "END;" in statements[1]
    assert '"semi;column"' in statements[2]


def test_postgres_executescript_executes_only_top_level_statements():
    executed: list[str] = []
    connection = DatabaseConnection.__new__(DatabaseConnection)
    connection.is_postgres = True
    connection._connection = SimpleNamespace(execute=lambda sql: executed.append(sql))

    connection.executescript(
        """
        -- description; not a statement boundary
        CREATE TABLE first_table (value TEXT DEFAULT 'x;y');
        CREATE TABLE second_table (id INTEGER);
        """
    )

    assert len(executed) == 2
    assert "description; not a statement boundary" in executed[0]
    assert "DEFAULT 'x;y'" in executed[0]
    assert "CREATE TABLE second_table" in executed[1]
