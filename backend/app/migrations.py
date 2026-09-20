from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


PROJECT_COLUMNS = {
    "sessions": "project_id",
    "project_tasks": "project_id",
    "incidents": "project_id",
}

DOCUMENT_COLUMNS = {
    "source_type": "VARCHAR(32) NOT NULL DEFAULT 'upload'",
    "source_url": "VARCHAR(1024)",
}


def migrate_legacy_schema(engine: Engine) -> None:
    """Add v0.2 workspace columns to databases created by earlier demos."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    column_type = "BIGINT" if dialect == "mysql" else "INTEGER"

    with engine.begin() as connection:
        for table, column in PROJECT_COLUMNS.items():
            if table not in tables:
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            if column not in columns:
                connection.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {column_type} NOT NULL DEFAULT 1"
                ))
        if "documents" in tables:
            columns = {item["name"] for item in inspector.get_columns("documents")}
            for column, definition in DOCUMENT_COLUMNS.items():
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE documents ADD COLUMN {column} {definition}"))
