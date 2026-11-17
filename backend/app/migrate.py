"""Bring an EXISTING database up to date with models.py (run automatically at every start).

`create_all` only creates missing TABLES. This also adds missing COLUMNS (nullable), and fills
default values for them, so nobody has to drop the database when a column is added.
You can also run it by hand:   python -m app.migrate
It is safe to run any number of times.
"""
from sqlalchemy import inspect, text, update
from sqlalchemy.engine import Engine

from .database import Base, engine as default_engine
from . import models  # noqa: F401  (registers every table on Base)

# (table, column, new length): text columns that were too short for Milestone 3 messages (PostgreSQL only)
WIDEN = [("activity_logs", "action", 500)]


def run(engine: Engine = None) -> list:
    engine = engine or default_engine
    changes = []
    Base.metadata.create_all(engine)  # new tables
    dialect = engine.dialect
    quote = dialect.identifier_preparer.quote

    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(column.name)} {column.type.compile(dialect=dialect)}"
            for fk in column.foreign_keys:
                ddl += f" REFERENCES {quote(fk.column.table.name)} ({quote(fk.column.name)})"
            with engine.begin() as conn:
                conn.execute(text(ddl))
                default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                if default is not None:  # e.g. users.is_active -> True for the rows that already exist
                    conn.execute(update(table).where(column.is_(None)).values({column.name: default}))
            changes.append(f"added column {table.name}.{column.name}")

    if dialect.name == "postgresql":
        for table_name, column_name, length in WIDEN:
            for col in inspect(engine).get_columns(table_name):
                current = getattr(col["type"], "length", None)
                if col["name"] == column_name and current is not None and current < length:
                    with engine.begin() as conn:
                        conn.execute(text(
                            f"ALTER TABLE {quote(table_name)} ALTER COLUMN {quote(column_name)} TYPE VARCHAR({length})"))
                    changes.append(f"widened {table_name}.{column_name} to {length}")
    return changes


if __name__ == "__main__":
    done = run()
    print("\n".join(done) if done else "Database is already up to date.")
