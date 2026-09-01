#!/usr/bin/env bash
# One-shot, safety-checked migration runner for VINCO's OWN isolated
# PostgreSQL schema (settings.staging_schema / VISION_STAGING_SCHEMA,
# "vinco" by default -- see app/core/config.py). Never touches `public`:
# that schema belongs to the Supabase project this backend authenticates
# against (Auth/RBAC tables, plus pre-existing UUID-keyed application
# tables that collide by name with several of VINCO's own -- see
# migrations/versions/926e160784a0_postgresql_baseline_schema.py's
# docstring). This script only ever creates/inspects the target schema
# named below; it issues no DDL against any other schema.
#
# Run this from the repo root with your venv already active. It:
#   1. Reads VISION_DATABASE_URL hidden if not already set in your shell.
#   2. Resolves the target schema from settings.staging_schema (defaults
#      to "vinco"; override by exporting VISION_STAGING_SCHEMA first).
#   3. Opens a READ-ONLY connection: lists existing tables in that schema
#      (should be empty/absent on a fresh bootstrap) and the current
#      Alembic revision recorded there, if any.
#   4. Works out, from Alembic's own revision chain, exactly which
#      migration(s) *should* run from that starting point -- including
#      the documented stamp-then-upgrade path for a from-scratch
#      PostgreSQL schema (see 926e160784a0_postgresql_baseline_schema.py's
#      docstring).
#   5. Statically scans only those migration file(s) for DROP TABLE,
#      DROP COLUMN, DELETE FROM, TRUNCATE (or the equivalent op.* calls),
#      and checks every table it would create against the target
#      schema's existing tables for a name collision.
#   6. Prints exactly what would run and what tables would be created.
#   7. Only if every check passes: runs the actual stamp (if needed) and
#      `alembic upgrade head` -- which, via the app's own schema-pinning
#      (app/database/schema_isolation.py), self-provisions the target
#      schema with `CREATE SCHEMA IF NOT EXISTS` before any other DDL --
#      then prints the final revision.
#
# Never modifies anything until every check above passes. Never prints
# VISION_DATABASE_URL or any credential.

set -uo pipefail

if [ -z "${VISION_DATABASE_URL:-}" ]; then
  read -rs -p "Paste VISION_DATABASE_URL (hidden, not saved to history): " VISION_DATABASE_URL
  echo
  export VISION_DATABASE_URL
fi

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

from app.core.config import normalize_postgres_url, settings

stamp_file = os.environ["STAMP_FILE"]
url = normalize_postgres_url(os.environ["VISION_DATABASE_URL"])
target_schema = settings.staging_schema
if not target_schema:
    print("[UNSAFE] settings.staging_schema is empty -- refusing to run against "
          "the default/unspecified schema. Set VISION_STAGING_SCHEMA explicitly.")
    sys.exit(1)

engine = create_engine(url, future=True)

print(f"=== [READ-ONLY] Connecting -- target schema: {target_schema!r} ===")
with engine.connect() as conn:
    existing_tables = sorted(
        r[0] for r in conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
            {"s": target_schema},
        )
    )
    try:
        current_rev = conn.execute(
            text(f'SELECT version_num FROM "{target_schema}".alembic_version')
        ).scalar()
    except Exception:
        current_rev = None
    # Connection closes here; nothing else is ever sent on it. Nothing
    # about this connection touches `public` or any schema other than
    # target_schema -- it doesn't even set search_path itself (that's
    # this same information_schema query filtering explicitly by name).

print(f"Existing tables in {target_schema!r} ({len(existing_tables)}):")
for t in existing_tables:
    print(f"  - {t}")
print(f"\nCurrent Alembic revision in {target_schema!r}: "
      f"{current_rev or '(none -- no alembic_version row)'}")

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
head = script.get_current_head()

# 926e160784a0 ("postgresql baseline schema") is a fixed, permanent
# historical revision: dialect-conditional, no-op on SQLite, creates
# the ENTIRE schema from scratch on PostgreSQL -- see that migration's
# own docstring for why (the 14 migrations before it contain SQLite-
# only DDL that fails partway through if replayed against Postgres).
# Its own predecessor (cb86207a716e) is the one fixed "skip to here"
# stamp target for any fresh PostgreSQL schema, regardless of how many
# migrations have been added on top of the baseline since (like this
# one). Everything from the baseline onward is normal, dialect-
# agnostic Alembic -- no further special-casing needed as the chain
# grows.
BASELINE_REVISION = "926e160784a0"

all_revs = list(script.walk_revisions(base="base", head=head))
all_revs.reverse()  # oldest first
order = {r.revision: i for i, r in enumerate(all_revs)}
baseline_idx = order[BASELINE_REVISION]
baseline_predecessor = all_revs[baseline_idx].down_revision

stamp_needed = None
if current_rev == head:
    to_run = []
elif current_rev is None:
    # Fresh schema: stamp the baseline's own predecessor (skips the
    # SQLite-only pre-baseline chain without executing it), then apply
    # the baseline AND everything after it, through head.
    to_run = all_revs[baseline_idx:]
    stamp_needed = baseline_predecessor
elif current_rev not in order:
    print(f"\n[UNSAFE] Current revision {current_rev!r} is not part of this "
          "migration chain at all. Refusing to guess a safe path -- this needs "
          "a human to look at the actual revision chain before proceeding.")
    sys.exit(1)
elif order[current_rev] == baseline_idx - 1:
    # Exactly at the baseline's prerequisite -- same fresh-schema path,
    # minus the stamp (already there).
    to_run = all_revs[baseline_idx:]
elif order[current_rev] < baseline_idx - 1:
    print(f"\n[UNSAFE] Current revision {current_rev!r} is partway through the "
          "SQLite-only pre-baseline chain on what appears to be a PostgreSQL "
          f"database (target schema {target_schema!r}) -- those migrations are "
          "known to fail if replayed against Postgres (see "
          f"{BASELINE_REVISION}'s docstring). Refusing to guess a safe path "
          "here -- this needs a human to look at the actual revision chain "
          "before proceeding.")
    sys.exit(1)
else:
    # At or after the baseline itself -- a completely normal walk
    # forward to head, however many migrations that now spans.
    to_run = all_revs[order[current_rev] + 1 :]

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

print(f"\nTables this run will CREATE in {target_schema!r} ({len(created_tables)}):")
for t in created_tables:
    print(f"  - {t}")

collisions = sorted(set(created_tables) & set(existing_tables))
duplicates_within_run = sorted({t for t in created_tables if created_tables.count(t) > 1})

if collisions:
    print(f"\n[UNSAFE] Table name collision with EXISTING tables in {target_schema!r}: {collisions}")
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

print(f"\n[SAFE] No destructive ops, no collisions, no duplicate creates in "
      f"{target_schema!r}. `public` is never referenced by this run. Proceeding.")
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
