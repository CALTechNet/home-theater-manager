"""Lightweight schema migrations.

Runs on startup. Handles the two changes we actually make in practice:
  1. New tables  -> created via metadata.create_all (idempotent).
  2. New columns -> detected by comparing the models to the live schema and
     applied with additive `ALTER TABLE ... ADD COLUMN`.

This is intentionally additive-only and safe to run repeatedly. Destructive or
data-transforming migrations would graduate to Alembic; until then this keeps
existing databases in sync without resetting the volume.
"""
import logging

from sqlalchemy import Boolean, Float, Integer, inspect, text
from sqlalchemy.engine import Engine

from .database import Base, engine as default_engine

log = logging.getLogger("htm.migrations")


def _type_sql(col, dialect) -> str:
    try:
        return col.type.compile(dialect=dialect)
    except Exception:  # noqa: BLE001 - fall back to a permissive type
        return "TEXT"


def _default_literal(col) -> str:
    """A SQL literal for the column's default (required by SQLite ADD COLUMN)."""
    d = col.default
    if d is not None and getattr(d, "is_scalar", False):
        val = d.arg
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, (int, float)):
            return str(val)
        return "'" + str(val).replace("'", "''") + "'"
    if isinstance(col.type, (Integer, Float, Boolean)):
        return "0"
    return "''"


def run_migrations(target_engine: Engine | None = None) -> list[str]:
    """Sync the live schema to the models. Returns a list of applied changes."""
    from . import models  # noqa: F401  (register models on Base)

    eng = target_engine or default_engine
    applied: list[str] = []

    # 1. New tables.
    Base.metadata.create_all(bind=eng)

    # 2. New columns on existing tables.
    insp = inspect(eng)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # freshly created above; already complete
        live_cols = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in live_cols:
                continue
            ddl = (
                f"ALTER TABLE {table.name} ADD COLUMN {col.name} "
                f"{_type_sql(col, eng.dialect)} DEFAULT {_default_literal(col)}"
            )
            with eng.begin() as conn:
                conn.execute(text(ddl))
            change = f"{table.name}.{col.name}"
            applied.append(change)
            log.info("migration: added column %s", change)

    if applied:
        log.info("migrations applied: %s", ", ".join(applied))
    return applied
