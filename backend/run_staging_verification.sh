#!/usr/bin/env bash
# ONE-COMMAND PostgreSQL staging verification.
#
# Usage:
#   ./run_staging_verification.sh
#
# Runs the full staging cutover check (connect, schema check, apply
# migration, dialect-compatibility tests, copy your real SQLite database,
# migrate the copy, verify row counts/financial totals/foreign keys/
# sequences, API smoke tests, confirm the original SQLite file is
# unchanged) and prints one PASS/FAIL report. See
# app/database/run_staging_verification.py for full details and safety
# properties -- this script only activates the virtualenv and hands off.
#
# If VISION_DATABASE_URL isn't already set in your shell, it will prompt
# you for it (and, optionally, a Supabase access token) with hidden
# input -- neither is ever written to shell history, a file, or stdout.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

exec python3 -m app.database.run_staging_verification
