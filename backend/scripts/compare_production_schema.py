#!/usr/bin/env python3
"""READ-ONLY comparison: production `public` schema vs VINCO's ORM metadata.

Issues ONLY SELECT statements -- no INSERT/UPDATE/DELETE, no DDL (no
CREATE/ALTER/DROP), no `alembic stamp`/`upgrade` call anywhere in this
file. For every table VINCO's models define, this reports:

  - Whether a same-named table already exists in production's `public`
    schema.
  - If it exists: its actual columns/types/nullable/defaults, primary
    key, foreign keys, indexes, unique constraints, and row count --
    each compared directly against what VINCO's SQLAlchemy models
    define for that table name -- plus a small (LIMIT 2) sample of its
    own rows, to help judge whether it's genuinely VINCO's table (an
    earlier partial migration, etc.) or an unrelated table that
    happens to share a name.
  - If it doesn't exist: just what VINCO would create there.

Run with your production VISION_DATABASE_URL (hidden prompt if not
already set in your shell). Never prints the connection string or any
credential. The row samples printed ARE real data from your database --
review before pasting this output anywhere you wouldn't paste raw
customer records.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.core.config import normalize_postgres_url
from app.database.base import Base


def expected_schema(table) -> dict:
    columns = []
    for c in table.columns:
        pg_type = c.type.compile(dialect=postgresql.dialect())
        default = None
        if c.server_default is not None:
            default = str(c.server_default.arg)
        columns.append(
            {
                "name": c.name,
                "type": pg_type,
                "nullable": c.nullable,
                "server_default": default,
            }
        )
    fks = [(fk.parent.name, fk.target_fullname) for fk in table.foreign_keys]
    uniques = []
    for constraint in table.constraints:
        if constraint.__class__.__name__ == "UniqueConstraint":
            uniques.append([c.name for c in constraint.columns])
    for c in table.columns:
        if c.unique:
            uniques.append([c.name])
    indexes = [
        {"name": ix.name, "columns": [c.name for c in ix.columns], "unique": ix.unique}
        for ix in table.indexes
    ]
    return {
        "columns": columns,
        "primary_key": list(table.primary_key.columns.keys()),
        "foreign_keys": fks,
        "unique_constraints": uniques,
        "indexes": indexes,
    }


def actual_schema(conn, table_name: str) -> dict:
    columns = []
    for row in conn.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, "
            "is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t "
            "ORDER BY ordinal_position"
        ),
        {"t": table_name},
    ):
        type_str = row.data_type
        if row.character_maximum_length:
            type_str = f"{type_str}({row.character_maximum_length})"
        columns.append(
            {
                "name": row.column_name,
                "type": type_str,
                "nullable": row.is_nullable == "YES",
                "default": row.column_default,
            }
        )

    pk = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = to_regclass(:t) AND i.indisprimary "
                "ORDER BY array_position(i.indkey, a.attnum)"
            ),
            {"t": f"public.{table_name}"},
        )
    ]

    fks = [
        (r.column_name, f"{r.foreign_table_name}.{r.foreign_column_name}")
        for r in conn.execute(
            text(
                """
                SELECT kcu.column_name, ccu.table_name AS foreign_table_name,
                       ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
                  AND tc.table_name = :t
                """
            ),
            {"t": table_name},
        )
    ]

    uniques = [
        r.column_name
        for r in conn.execute(
            text(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'UNIQUE' AND tc.table_schema = 'public'
                  AND tc.table_name = :t
                """
            ),
            {"t": table_name},
        )
    ]

    indexes = [
        {"name": r.indexname, "def": r.indexdef}
        for r in conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"),
            {"t": table_name},
        )
    ]

    row_count = conn.execute(text(f'SELECT count(*) FROM public."{table_name}"')).scalar_one()

    sample = []
    if row_count:
        result = conn.execute(text(f'SELECT * FROM public."{table_name}" LIMIT 2'))
        sample = [dict(r._mapping) for r in result]

    return {
        "columns": columns,
        "primary_key": pk,
        "foreign_keys": fks,
        "unique_constraints": uniques,
        "indexes": indexes,
        "row_count": row_count,
        "sample_rows": sample,
    }


def print_table_report(name: str, exists: bool, expected: dict, actual: dict | None) -> None:
    print("=" * 78)
    print(f"TABLE: {name}   ({'EXISTS in production public' if exists else 'does not exist yet'})")
    print("=" * 78)

    print("\n--- VINCO expects ---")
    for c in expected["columns"]:
        nn = "NOT NULL" if not c["nullable"] else "nullable"
        dflt = f" default={c['server_default']}" if c["server_default"] else ""
        print(f"  {c['name']}: {c['type']} {nn}{dflt}")
    print(f"  PK: {expected['primary_key']}")
    print(f"  FKs: {expected['foreign_keys']}")
    print(f"  unique: {expected['unique_constraints']}")
    print(f"  indexes: {expected['indexes']}")

    if not exists:
        print("\n(nothing to compare -- table absent, VINCO's migration would create it as above)\n")
        return

    print("\n--- Production actually has ---")
    for c in actual["columns"]:
        nn = "NOT NULL" if not c["nullable"] else "nullable"
        dflt = f" default={c['default']}" if c["default"] else ""
        print(f"  {c['name']}: {c['type']} {nn}{dflt}")
    print(f"  PK: {actual['primary_key']}")
    print(f"  FKs: {actual['foreign_keys']}")
    print(f"  unique: {actual['unique_constraints']}")
    print(f"  indexes: {[ix['def'] for ix in actual['indexes']]}")
    print(f"  row count: {actual['row_count']}")

    expected_cols = {c["name"] for c in expected["columns"]}
    actual_cols = {c["name"] for c in actual["columns"]}
    only_expected = sorted(expected_cols - actual_cols)
    only_actual = sorted(actual_cols - expected_cols)
    shared = sorted(expected_cols & actual_cols)
    print("\n--- Diff ---")
    print(f"  columns only in VINCO's model (missing from production): {only_expected}")
    print(f"  columns only in production (not in VINCO's model): {only_actual}")
    print(f"  columns in both: {len(shared)}/{len(expected_cols)} VINCO columns present")

    overlap_ratio = len(shared) / max(len(expected_cols), 1)
    verdict = (
        "LIKELY VINCO's own table (or an earlier/partial VINCO migration)"
        if overlap_ratio > 0.6
        else "LIKELY an UNRELATED table that happens to share this name (e.g. Supabase's own)"
    )
    print(f"  verdict: {verdict}  ({overlap_ratio:.0%} column-name overlap)")

    if actual["sample_rows"]:
        print(f"\n  sample rows (LIMIT 2 of {actual['row_count']}):")
        for row in actual["sample_rows"]:
            print(f"    {row}")
    else:
        print("\n  (table is empty -- no sample rows)")
    print()


def main() -> int:
    url = normalize_postgres_url(os.environ["VISION_DATABASE_URL"])
    engine = create_engine(url, future=True)

    with engine.connect() as conn:
        existing_tables = {
            r[0]
            for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
        }
        print(f"Production public schema currently has {len(existing_tables)} table(s).\n")

        collisions = []
        clean_creates = []
        for table in Base.metadata.sorted_tables:
            expected = expected_schema(table)
            exists = table.name in existing_tables
            actual = actual_schema(conn, table.name) if exists else None
            print_table_report(table.name, exists, expected, actual)
            (collisions if exists else clean_creates).append(table.name)

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"Colliding tables ({len(collisions)}): {collisions}")
    print(f"Clean creates ({len(clean_creates)}): {clean_creates}")
    unrelated_production_tables = sorted(existing_tables - {t.name for t in Base.metadata.sorted_tables})
    print(f"Production tables VINCO's models don't mention at all ({len(unrelated_production_tables)}): "
          f"{unrelated_production_tables}")
    print("\nNo changes were made. This script issued SELECT statements only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
