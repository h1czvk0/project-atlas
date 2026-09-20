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

PROJECT_METADATA_COLUMNS = {
    "repo_status": "VARCHAR(32) NOT NULL DEFAULT 'not_imported'",
    "repo_local_path": "VARCHAR(512)",
    "repo_last_commit": "VARCHAR(64)",
    "repo_indexed_files": "INTEGER NOT NULL DEFAULT 0",
    "repo_progress": "INTEGER NOT NULL DEFAULT 0",
    "repo_stage": "VARCHAR(64) NOT NULL DEFAULT '等待导入'",
    "repo_error": "TEXT",
    "repo_last_synced_at": "DATETIME",
}


def migrate_legacy_schema(engine: Engine) -> None:
    """Add v0.2 workspace columns to databases created by earlier demos."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    column_type = "BIGINT" if dialect == "mysql" else "INTEGER"

    with engine.begin() as connection:
        if "projects" in tables:
            columns = {item["name"] for item in inspector.get_columns("projects")}
            for column, definition in PROJECT_METADATA_COLUMNS.items():
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE projects ADD COLUMN {column} {definition}"))
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
