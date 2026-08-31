#!/usr/bin/env bash
# One-shot, safety-checked production migration runner.
#
# Run this from the repo root with your venv already active. It:
#   1. Reads VISION_DATABASE_URL hidden if not already set in your shell.
#   2. Unsets VISION_STAGING_SCHEMA (must target `public`, not a staging schema).
#   3. Opens a READ-ONLY connection: lists existing public tables, reads the
#      current Alembic revision (if any).
#   4. Works out, from Alembic's own revision chain, exactly which
#      migration(s) *should* run from that starting point -- including the
#      documented stamp-then-upgrade path for a from-scratch PostgreSQL
#      database (see 926e160784a0_postgresql_baseline_schema.py's docstring).
#   5. Statically scans only those migration file(s) for DROP TABLE,
#      DROP COLUMN, DELETE FROM, TRUNCATE (or the equivalent op.* calls),
#      and checks every table it would create against the existing-tables
#      list for a name collision.
#   6. Prints exactly what would run and what tables would be created.
#   7. Only if every check passes: runs the actual stamp (if needed) and
#      `alembic upgrade head`, then prints the final revision.
#
# Never modifies anything until every check above passes. Never prints
# VISION_DATABASE_URL or any credential.

set -uo pipefail

if [ -z "${VISION_DATABASE_URL:-}" ]; then
  read -rs -p "Paste VISION_DATABASE_URL (hidden, not saved to history): " VISION_DATABASE_URL
  echo
  export VISION_DATABASE_URL
fi
unset VISION_STAGING_SCHEMA

export STAMP_FILE
STAMP_FILE="$(mktemp)"
trap 'rm -f "$STAMP_FILE"' EXIT

python3 <<'PYEOF'
import os
import re
import sys

from sqlalchemy import create_engine, text

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import normalize_postgres_url

stamp_file = os.environ["STAMP_FILE"]
url = normalize_postgres_url(os.environ["VISION_DATABASE_URL"])
engine = create_engine(url, future=True)

print("=== [READ-ONLY] Connecting ===")
with engine.connect() as conn:
    existing_tables = sorted(
        r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ))
    )
    try:
        current_rev = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
    except Exception:
        current_rev = None
    # Connection closes here; nothing else is ever sent on it.

print(f"Existing public tables ({len(existing_tables)}):")
for t in existing_tables:
    print(f"  - {t}")
print(f"\nCurrent Alembic revision in public: {current_rev or '(none -- no alembic_version row)'}")

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
head = script.get_current_head()
head_rev = script.get_revision(head)
baseline_predecessor = head_rev.down_revision  # read dynamically, not hardcoded

stamp_needed = None
if current_rev == head:
    to_run = []
elif current_rev is None:
    # Fresh database: the documented path is `stamp <predecessor>` (no DDL)
    # then `upgrade head`, which then applies only head_rev for real.
    to_run = [head_rev]
    stamp_needed = baseline_predecessor
elif current_rev == baseline_predecessor:
    to_run = [head_rev]
else:
    print(f"\n[UNSAFE] Unexpected current revision {current_rev!r} -- not empty, "
          f"not {baseline_predecessor!r} (the baseline migration's prerequisite), "
          f"and not head ({head!r}). Refusing to guess a safe path here -- this "
          "needs a human to look at the actual revision chain before proceeding.")
    sys.exit(1)

print(f"\nMigration(s) that WILL run ({len(to_run)}):")
for rev in to_run:
    print(f"  - {rev.revision}: {rev.doc}")
if stamp_needed:
    print(f"\n(Will first run: alembic stamp {stamp_needed}  -- bookkeeping only, no DDL)")

DANGEROUS = re.compile(
    r"\bop\.(drop_table|drop_column|drop_index|drop_constraint)\b|"
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|DELETE\s+FROM|TRUNCATE)\b",
    re.IGNORECASE,
)
CREATE_TABLE = re.compile(r"op\.create_table\(\s*['\"]([a-zA-Z0-9_]+)['\"]")

created_tables = []
dangerous_hits = []
for rev in to_run:
    src = open(rev.path, encoding="utf-8").read()
    upgrade_src = src.split("def downgrade", 1)[0]  # never scan downgrade()
    for m in DANGEROUS.finditer(upgrade_src):
        dangerous_hits.append((rev.revision, m.group(0)))
    for m in CREATE_TABLE.finditer(upgrade_src):
        created_tables.append(m.group(1))

print(f"\nTables this run will CREATE ({len(created_tables)}):")
for t in created_tables:
    print(f"  - {t}")

collisions = sorted(set(created_tables) & set(existing_tables))
duplicates_within_run = sorted({t for t in created_tables if created_tables.count(t) > 1})

if collisions:
    print(f"\n[UNSAFE] Table name collision with EXISTING public tables: {collisions}")
    sys.exit(1)
if duplicates_within_run:
    print(f"\n[UNSAFE] The migration(s) about to run would create the same table "
          f"more than once: {duplicates_within_run} -- this means the revision "
          "range is wrong (would fail partway through with DuplicateTable). "
          "Refusing to proceed.")
    sys.exit(1)
if dangerous_hits:
    print("\n[UNSAFE] Destructive operation(s) found:")
    for rev, hit in dangerous_hits:
        print(f"  - {rev}: {hit}")
    sys.exit(1)
if not to_run:
    print("\n[OK] Already at head -- nothing to migrate.")
    sys.exit(3)

print("\n[SAFE] No destructive ops, no collisions, no duplicate creates. Proceeding.")
with open(stamp_file, "w") as f:
    f.write(stamp_needed or "")
sys.exit(0)
PYEOF
RC=$?

if [ "$RC" -eq 0 ]; then
  STAMP_TARGET="$(cat "$STAMP_FILE")"
  echo
  echo "=== Safety checks passed. Applying. ==="
  if [ -n "$STAMP_TARGET" ]; then
    echo "--- alembic stamp $STAMP_TARGET ---"
    alembic stamp "$STAMP_TARGET" || { echo "Stamp failed -- stopping, upgrade head was NOT run."; exit 1; }
  fi
  echo "--- alembic upgrade head ---"
  alembic upgrade head
  echo
  echo "=== Final Alembic revision ==="
  alembic current
elif [ "$RC" -eq 3 ]; then
  echo
  echo "Nothing to do -- already at head."
else
  echo
  echo "Safety checks FAILED -- nothing was run against the database. Review the output above."
  exit "$RC"
fi
