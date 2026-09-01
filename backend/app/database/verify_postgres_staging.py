"""Read-only verification for a SQLite -> PostgreSQL staging cutover.

Run this AFTER `migrate_sqlite_to_postgres.py` has copied data from a
SQLite database (always a COPY of the real one, never the original file)
into a PostgreSQL database that already has the baseline schema applied.
This script makes no writes to either database -- it only compares them
and reports discrepancies:

    python -m app.database.verify_postgres_staging \\
        --source sqlite:///path/to/copy.db \\
        --target "$VISION_DATABASE_URL"

Checks performed:
  1. Row counts for every table, source vs target.
  2. Key financial totals (sums), source vs target.
  3. Foreign key referential integrity on the target (orphan scan --
     Postgres enforces FKs at write time, so this is a belt-and-braces
     re-check rather than something that should ever fail if the copy
     succeeded cleanly).
  4. Every integer-PK table's PostgreSQL sequence is at or beyond
     MAX(id), so the next INSERT can't collide with a migrated row.

Exits with a non-zero status if any check fails, so it can gate a
cutover decision without a human having to read the whole report.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.core.config import normalize_postgres_url
from app.database.base import Base
from app.database.schema_isolation import pin_search_path_from_settings
from app.models.contract import Contract
from app.models.cost import ActualCost
from app.models.employee import PayrollRecord
from app.models.invoice import Invoice, Payment
from app.models.project import Project
from app.models.quotation import QuotationVersion

FINANCIAL_METRICS = [
    ("quotations.quoted_value", QuotationVersion.__table__, QuotationVersion.quoted_value),
    ("contracts.value", Contract.__table__, Contract.value),
    ("projects.contract_value", Project.__table__, Project.contract_value),
    ("invoices.amount", Invoice.__table__, Invoice.amount),
    ("payments.amount", Payment.__table__, Payment.amount),
    ("actual_costs.amount (expenses)", ActualCost.__table__, ActualCost.amount),
    ("payroll_records.gross_amount", PayrollRecord.__table__, PayrollRecord.gross_amount),
    ("payroll_records.net_amount", PayrollRecord.__table__, PayrollRecord.net_amount),
]


def compare_row_counts(source: Engine, target: Engine) -> bool:
    print("\n=== Row counts (source SQLite vs target PostgreSQL) ===")
    all_ok = True
    with source.connect() as sc, target.connect() as tc:
        for table in Base.metadata.sorted_tables:
            s_count = sc.execute(select(func.count()).select_from(table)).scalar_one()
            t_count = tc.execute(select(func.count()).select_from(table)).scalar_one()
            ok = s_count == t_count
            all_ok &= ok
            marker = "OK" if ok else "MISMATCH"
            if s_count or t_count:
                print(f"  [{marker}] {table.name}: source={s_count} target={t_count}")
    return all_ok


def compare_financial_totals(source: Engine, target: Engine) -> bool:
    print("\n=== Financial totals (source SQLite vs target PostgreSQL) ===")
    all_ok = True
    with source.connect() as sc, target.connect() as tc:
        for label, table, column in FINANCIAL_METRICS:
            s_total = sc.execute(select(func.sum(column)).select_from(table)).scalar_one() or Decimal(0)
            t_total = tc.execute(select(func.sum(column)).select_from(table)).scalar_one() or Decimal(0)
            ok = Decimal(s_total) == Decimal(t_total)
            all_ok &= ok
            marker = "OK" if ok else "MISMATCH"
            print(f"  [{marker}] {label}: source={s_total} target={t_total}")
    return all_ok


def check_foreign_key_integrity(target: Engine) -> bool:
    print("\n=== Foreign key referential integrity (target PostgreSQL only) ===")
    all_ok = True
    with target.connect() as conn:
        for table in Base.metadata.sorted_tables:
            for fk in table.foreign_key_constraints:
                if len(fk.columns) != 1:
                    continue  # all FKs in this schema are single-column
                local_col = next(iter(fk.columns))
                remote_col = next(iter(fk.elements)).column
                orphan_count = conn.execute(
                    text(
                        f'SELECT count(*) FROM "{table.name}" t '
                        f'WHERE t."{local_col.name}" IS NOT NULL '
                        f'AND NOT EXISTS (SELECT 1 FROM "{remote_col.table.name}" r '
                        f'WHERE r."{remote_col.name}" = t."{local_col.name}")'
                    )
                ).scalar_one()
                ok = orphan_count == 0
                all_ok &= ok
                if orphan_count:
                    print(f"  [MISMATCH] {table.name}.{local_col.name} -> {remote_col.table.name}: {orphan_count} orphan row(s)")
    if all_ok:
        print("  [OK] no orphaned foreign keys found")
    return all_ok


def check_sequences(target: Engine) -> bool:
    print("\n=== Sequence positions (target PostgreSQL only) ===")
    all_ok = True
    with target.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if "id" not in table.columns:
                continue
            max_id = conn.execute(text(f'SELECT MAX(id) FROM "{table.name}"')).scalar_one()
            if max_id is None:
                continue
            seq_value = conn.execute(
                text(
                    "SELECT last_value FROM pg_sequences WHERE schemaname = current_schema() "
                    "AND sequencename = split_part(pg_get_serial_sequence(:t, 'id'), '.', 2)"
                ),
                {"t": table.name},
            ).scalar()
            ok = seq_value is not None and seq_value >= max_id
            all_ok &= ok
            marker = "OK" if ok else "MISMATCH"
            print(f"  [{marker}] {table.name}: MAX(id)={max_id} sequence last_value={seq_value}")
    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Source SQLite SQLAlchemy URL (a COPY, never the original file)")
    parser.add_argument("--target", required=True, help="Target PostgreSQL SQLAlchemy URL")
    args = parser.parse_args()
    args.source = normalize_postgres_url(args.source)
    args.target = normalize_postgres_url(args.target)

    if not args.target.startswith("postgresql"):
        print(f"Refusing to run: target URL is not PostgreSQL: {args.target}", file=sys.stderr)
        raise SystemExit(1)

    source_engine = create_engine(args.source, future=True)
    target_engine = create_engine(args.target, future=True)
    pin_search_path_from_settings(target_engine)

    results = [
        compare_row_counts(source_engine, target_engine),
        compare_financial_totals(source_engine, target_engine),
        check_foreign_key_integrity(target_engine),
        check_sequences(target_engine),
    ]

    print("\n=== Summary ===")
    if all(results):
        print("ALL CHECKS PASSED")
        raise SystemExit(0)
    print("ONE OR MORE CHECKS FAILED -- see MISMATCH lines above")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
