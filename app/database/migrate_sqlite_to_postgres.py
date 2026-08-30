"""One-time SQLite -> PostgreSQL data migration tool.

Copies every row from an existing SQLite business database into a
PostgreSQL database that already has the schema applied (via
`alembic stamp cb86207a716e && alembic upgrade head` -- see the
`926e160784a0_postgresql_baseline_schema` migration's docstring). This
script only moves data; it never creates or alters schema.

NEVER imported by application code or run automatically -- this is a
deliberate, explicit, one-shot operation an operator runs by hand when
actually cutting over to production PostgreSQL:

    python -m app.database.migrate_sqlite_to_postgres \\
        --source sqlite:////path/to/vision_contracting.db \\
        --target postgresql+psycopg://user:pass@host:5432/dbname \\
        --yes

Safety properties:

- Refuses to run unless `--yes` is passed (a no-op dry run without it
  just reports what it *would* copy).
- Refuses to write into a target database that already has any rows in
  any of the tables being migrated, to avoid silently duplicating or
  clobbering data on a re-run -- pass `--force` to override.
- Copies all tables inside a single target-side transaction: a failure
  partway through rolls back the entire migration, never leaving the
  target half-populated.
- Copies rows in FK-dependency order (`Base.metadata.sorted_tables`) so
  foreign key constraints are satisfied as each table is inserted.
- Re-synchronizes every PostgreSQL identity/serial sequence to
  MAX(id) after copying, since rows are inserted with their original
  explicit ids rather than letting the sequence assign new ones.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, func, select, text

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.database.base import Base
from app.database.schema_isolation import pin_search_path_from_settings


def _row_counts(engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            counts[table.name] = conn.execute(select(func.count()).select_from(table)).scalar_one()
    return counts


def _copy_table(source_conn, target_conn, table) -> int:
    rows = [dict(row._mapping) for row in source_conn.execute(select(table))]
    if rows:
        target_conn.execute(table.insert(), rows)
    return len(rows)


def _reset_postgres_sequence(target_conn, table) -> None:
    if "id" not in table.columns:
        return
    target_conn.execute(
        text(
            "SELECT setval("
            "pg_get_serial_sequence(:table_name, 'id'), "
            "COALESCE((SELECT MAX(id) FROM " + table.name + "), 1), "
            "(SELECT MAX(id) FROM " + table.name + ") IS NOT NULL"
            ")"
        ),
        {"table_name": table.name},
    )


def migrate(source_url: str, target_url: str, *, dry_run: bool, force: bool) -> int:
    source_engine = create_engine(source_url, future=True)
    target_engine = create_engine(target_url, future=True)
    pin_search_path_from_settings(target_engine)

    if not target_url.startswith("postgresql"):
        print(f"Refusing to run: target URL is not a PostgreSQL URL: {target_url}", file=sys.stderr)
        return 1

    source_counts = _row_counts(source_engine)
    target_counts = _row_counts(target_engine)

    print("Source row counts (SQLite):")
    for name, count in source_counts.items():
        if count:
            print(f"  {name}: {count}")
    total_source_rows = sum(source_counts.values())
    print(f"Total source rows: {total_source_rows}")

    existing_target_rows = sum(target_counts.values())
    if existing_target_rows and not force:
        print(
            f"\nRefusing to run: target database already has {existing_target_rows} row(s) "
            "across its tables. Pass --force to migrate into a non-empty target anyway "
            "(existing rows are left in place; this can create duplicate primary keys).",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print("\nDry run only (pass --yes to actually copy data). No changes made.")
        return 0

    with target_engine.begin() as target_conn:
        with source_engine.connect() as source_conn:
            for table in Base.metadata.sorted_tables:
                copied = _copy_table(source_conn, target_conn, table)
                if copied:
                    _reset_postgres_sequence(target_conn, table)
                    print(f"Copied {copied} row(s) into {table.name}")

    print("\nMigration complete.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Source SQLite SQLAlchemy URL, e.g. sqlite:///path/to.db")
    parser.add_argument("--target", required=True, help="Target PostgreSQL SQLAlchemy URL")
    parser.add_argument(
        "--yes", action="store_true", help="Actually copy data (omit for a dry run that only reports row counts)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Allow migrating into a target database that already has rows"
    )
    args = parser.parse_args()

    exit_code = migrate(args.source, args.target, dry_run=not args.yes, force=args.force)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
