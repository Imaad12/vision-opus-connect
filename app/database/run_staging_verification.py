"""ONE-COMMAND PostgreSQL staging verification.

Runs the entire staging cutover check end-to-end against an ISOLATED
PostgreSQL SCHEMA inside your existing database (never your `public`
schema) and a COPY of the real local SQLite business database:

    python -m app.database.run_staging_verification

This never touches, reads, or writes anything in `public` (or any other
pre-existing schema). It works entirely inside its own dedicated schema
(named by VISION_STAGING_SCHEMA, default "vinco_staging") within the same
database VISION_DATABASE_URL already points at -- no new connection
string, no new Supabase project, no CREATE DATABASE privilege needed.
Every connection this script makes sets its PostgreSQL `search_path` to
that schema alone, so unqualified table/sequence lookups can never
resolve to `public`. It owns that schema's entire lifecycle -- each run
starts by dropping and recreating it from scratch -- which is safe to do
without asking, because nothing but a previous run of this exact script
could ever have put anything there.

What it does, in this order (note: the PostgreSQL-compatibility test
suite runs BEFORE any real data is copied in, not after, even though a
literal reading of "copy data, then run compatibility tests" would put
it later -- those tests call `Base.metadata.drop_all()` on the target at
teardown, which would silently destroy the staged data copy if run
afterward; running them first, while the schema is still empty, is
lossless and covers exactly the same ground):

  1.  Read the PostgreSQL connection string from VISION_DATABASE_URL, or
      prompt for it (hidden input, never touches shell history).
  2.  Connect and verify the server is reachable.
  3.  Drop and recreate the isolated staging schema (never `public`).
  4.  Run the PostgreSQL dialect-compatibility tests against the (still
      empty) staging schema.
  5.  Apply the PostgreSQL baseline migration (`alembic stamp` +
      `alembic upgrade head`) inside the staging schema.
  6.  Locate the real local SQLite database and make a timestamped COPY
      of it -- every later step operates on the copy, never the
      original. The original's checksum is recorded now and re-checked
      at the very end.
  7.  Migrate the copy's data into the now-empty staging schema.
  8.  Compare row counts, key financial totals, foreign-key referential
      integrity, and sequence positions between the copy and the staging
      schema.
  9.  Start the FastAPI app against the staging schema on a scratch local
      port and run smoke tests: /health, and a protected endpoint
      without a token (must be rejected). Optionally, if you paste a
      Supabase access token when prompted (also hidden input,
      skippable), it also exercises one authenticated create -> read ->
      cleanup cycle.
  10. Re-verify the original SQLite file's checksum is unchanged.
  11. Print one PASS/FAIL report covering everything above.

Nothing about your VISION_DATABASE_URL, its password, or any token you
paste in is ever printed, logged, or written to a file by this script;
anything that could plausibly appear in an error message is redacted
before being shown.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The dedicated, isolated schema this script creates, uses, and resets
#: on every run -- never `public`, never any pre-existing schema.
STAGING_SCHEMA = os.environ.get("VISION_STAGING_SCHEMA", "vinco_staging")


class StagingCheckFailed(Exception):
    pass


def build_engine_url(raw: str, schema: str) -> URL:
    """Parse a possibly-malformed connection string into a structured
    URL, tolerating two things real users actually run into: no
    '+psycopg' driver suffix, and a password containing a raw '@' (which
    is otherwise ambiguous in a URI, since '@' is also the credentials/
    host separator -- splitting on the LAST '@' resolves it correctly
    because a hostname itself never contains '@').

    Also forces every connection's PostgreSQL `search_path` to `schema`
    alone (preserving any other query parameters already present, e.g.
    `sslmode`), so every unqualified table/sequence lookup this script or
    the app makes resolves inside the isolated staging schema and can
    never reach `public`."""
    raw = raw.strip()
    if "://" not in raw:
        raise StagingCheckFailed("Connection string must include a scheme, e.g. postgresql://...")
    _scheme, rest = raw.split("://", 1)
    if "@" not in rest:
        raise StagingCheckFailed("Connection string must be in user:password@host form.")
    creds, hostpart = rest.rsplit("@", 1)
    if ":" not in creds:
        raise StagingCheckFailed("Connection string is missing a password (user:password@...).")
    user, password = creds.split(":", 1)
    if "/" in hostpart:
        hostport, dbpart = hostpart.split("/", 1)
    else:
        hostport, dbpart = hostpart, ""
    if "?" in dbpart:
        database, query_string = dbpart.split("?", 1)
        query = dict(parse_qsl(query_string))
    else:
        database, query = dbpart, {}
    database = database.strip("/") or "postgres"
    if ":" in hostport:
        host, port_s = hostport.split(":", 1)
        try:
            port = int(port_s)
        except ValueError as exc:
            raise StagingCheckFailed(f"Invalid port in connection string: {port_s!r}") from exc
    else:
        host, port = hostport, 5432
    if not host:
        raise StagingCheckFailed("Connection string is missing a host.")

    search_path_opt = f"-csearch_path={schema}"
    query["options"] = f"{query['options']} {search_path_opt}" if query.get("options") else search_path_opt

    return URL.create(
        "postgresql+psycopg", username=user, password=password, host=host, port=port, database=database, query=query
    )


def make_redactor(*secrets: str):
    values = [s for s in secrets if s]

    def redact(text_: str) -> str:
        for s in values:
            text_ = text_.replace(s, "***REDACTED***")
        return text_

    return redact


def get_database_url() -> str:
    raw = os.environ.get("VISION_DATABASE_URL")
    if raw:
        print("[1/11] Using VISION_DATABASE_URL from your environment.")
        return raw
    print("[1/11] VISION_DATABASE_URL is not set in your environment.")
    raw = getpass.getpass("        Paste your Supabase Session Pooler connection string (hidden, not saved to history): ").strip()
    if not raw:
        raise StagingCheckFailed("No connection string provided.")
    return raw


def check_connection(engine, redact) -> str:
    print("[2/11] Connecting to PostgreSQL...")
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
    except Exception as exc:
        raise StagingCheckFailed(f"Could not connect: {_defensive_redact(redact(str(exc)))}") from exc
    short_version = version.split(",")[0]
    print(f"        Connected OK ({short_version})")
    return short_version


def reset_staging_schema(engine, schema: str) -> None:
    """Drop and recreate the isolated staging schema. Safe to do without
    asking: `schema` is a name this script owns end to end (default
    "vinco_staging"), never `public` or anything pre-existing, so nothing
    could be in it except leftovers from a previous run of this exact
    tool -- and this uses DROP SCHEMA, never DROP DATABASE or anything
    that could reach outside that one namespace."""
    print(f"[3/11] Creating an isolated staging schema '{schema}' (never touching public)...")
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    print(f"        Schema '{schema}' is ready and empty. Your public schema was not touched.")

    # Belt-and-braces: prove the isolation is actually in effect on THIS
    # connection before anything else runs. `search_path` is set via a
    # `-c search_path=...` startup option on the connection string; some
    # connection poolers don't forward startup options to the real
    # backend, which would silently leave every later operation (compat
    # tests, the baseline migration) pointed at `public` -- exactly the
    # database this script must never touch. Fail loudly here instead of
    # letting that surface later as a confusing error against whatever
    # unrelated tables already live in public.
    with engine.connect() as conn:
        actual_schema = conn.execute(text("SELECT current_schema()")).scalar()
    if actual_schema != schema:
        raise StagingCheckFailed(
            f"Isolation check failed: expected current_schema() = '{schema}' but got "
            f"'{actual_schema}'. Your connection pooler is not honoring the "
            "'-c search_path=...' startup option, so operations would silently run "
            "against the wrong schema (likely 'public'). Refusing to proceed -- "
            "nothing has been created or modified beyond the isolated schema itself."
        )
    print(f"        Verified: this connection is isolated to '{schema}' (current_schema() confirmed).")


def run_subprocess(cmd: list[str], env: dict, redact, cwd: Path = REPO_ROOT) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    output = redact(proc.stdout + proc.stderr)
    return proc.returncode == 0, output


#: Generic defense-in-depth redaction applied on top of the specific-value
#: redactor (`make_redactor`) before anything is written to disk or
#: printed on a failure path -- catches any URI-shaped credential that
#: the specific-value redactor might miss (e.g. a differently re-encoded
#: form of the same URL logged by a library).
_URI_CREDENTIAL_RE = re.compile(r"[a-zA-Z][\w+.-]*://[^@\s]+@")


def _defensive_redact(text_: str) -> str:
    return _URI_CREDENTIAL_RE.sub("***REDACTED***@", text_)


def _save_and_print_failure(output: str, label: str, tail_lines: int = 60) -> Path:
    """Persist an already-redacted subprocess's combined stdout/stderr to a
    temp file and print the tail of it immediately, so a failure is never
    silently swallowed by an early abort before the final report would
    otherwise have shown it. Applies a second, generic redaction pass on
    top of whatever specific-value redaction the caller already did."""
    output = _defensive_redact(output)
    log_path = Path(tempfile.gettempdir()) / f"vinco_staging_{label}_{os.getpid()}.log"
    log_path.write_text(output)
    print(f"        FAILED -- full output saved to: {log_path}")
    print(f"        Last {tail_lines} lines:")
    for line in output.splitlines()[-tail_lines:]:
        print("        | " + line)
    return log_path


def run_compat_tests(canonical_url: str, base_env: dict, redact) -> tuple[bool, str]:
    print("[4/11] Running PostgreSQL dialect-compatibility tests (target still empty)...")
    env = {**base_env, "VISION_TEST_POSTGRES_URL": canonical_url}
    ok, output = run_subprocess([sys.executable, "-m", "pytest", "app/tests/test_postgres_compat.py", "-v"], env, redact)
    if ok:
        print("        PASSED")
    else:
        _save_and_print_failure(output, "compat_tests")
    return ok, output


def apply_baseline_migration(canonical_url: str, base_env: dict, redact) -> tuple[bool, str]:
    print("[5/11] Applying the PostgreSQL baseline migration...")
    env = {**base_env, "VISION_DATABASE_URL": canonical_url}
    ok1, out1 = run_subprocess([sys.executable, "-m", "alembic", "stamp", "cb86207a716e"], env, redact)
    if not ok1:
        _save_and_print_failure(out1, "migration_stamp")
        return False, out1
    ok2, out2 = run_subprocess([sys.executable, "-m", "alembic", "upgrade", "head"], env, redact)
    if ok2:
        print("        PASSED")
    else:
        _save_and_print_failure(out1 + "\n" + out2, "migration_upgrade")
    return ok2, out1 + "\n" + out2


def locate_sqlite_db() -> Path:
    env_path = os.environ.get("VISION_DATABASE_PATH")
    candidate = Path(env_path) if env_path else REPO_ROOT / "vision_contracting.db"
    if not candidate.exists():
        entered = input(f"        Real SQLite database not found at {candidate} -- enter its full path: ").strip()
        candidate = Path(entered)
    if not candidate.exists():
        raise StagingCheckFailed(f"SQLite database not found at {candidate}")
    return candidate


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def make_copy(original: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    copy_path = Path(tempfile.gettempdir()) / f"vinco_staging_copy_{ts}.db"
    shutil.copy2(original, copy_path)
    return copy_path


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server_log_tail(log_path: Path, redact, n: int = 15) -> str:
    try:
        text_ = _defensive_redact(redact(log_path.read_text(errors="replace")))
    except OSError:
        return ""
    return "\n".join("        | " + ln for ln in text_.splitlines()[-n:])


def run_api_smoke_tests(canonical_url: str, base_env: dict, redact) -> tuple[bool, list[str]]:
    print("[9/11] Starting the API against PostgreSQL for smoke tests...")
    port = find_free_port()
    env = {**base_env, "VISION_DATABASE_URL": canonical_url}
    log_path = Path(tempfile.gettempdir()) / f"vinco_staging_api_{port}.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )
    lines: list[str] = []
    all_ok = True
    try:
        base = f"http://127.0.0.1:{port}"
        ready = False
        for _ in range(40):
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        if not ready:
            lines.append("  [FAIL] API did not become ready in time")
            lines.append(_server_log_tail(log_path, redact))
            return False, lines

        r = httpx.get(f"{base}/health", timeout=5)
        ok = r.status_code == 200
        all_ok &= ok
        lines.append(f"  [{'OK' if ok else 'FAIL'}] GET /health -> {r.status_code}")

        r = httpx.get(f"{base}/clients", timeout=5)
        ok = r.status_code in (401, 403)
        all_ok &= ok
        lines.append(f"  [{'OK' if ok else 'FAIL'}] GET /clients without auth -> {r.status_code} (expected 401/403)")
        if not ok:
            # FastAPI correctly hides the real exception from the HTTP
            # response body on a 500 -- the actual cause (most likely
            # VISION_SUPABASE_URL/VISION_SUPABASE_ANON_KEY not configured
            # in this shell, an auth-layer gap unrelated to PostgreSQL --
            # it would happen against SQLite too) is only in the server's
            # own log.
            lines.append("        Server log (most recent lines):")
            lines.append(_server_log_tail(log_path, redact))

        token = getpass.getpass(
            "        Optional: paste a Supabase access token to test authenticated CRUD "
            "(hidden, press Enter to skip): "
        ).strip()
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            r = httpx.get(f"{base}/clients", headers=headers, timeout=5)
            ok = r.status_code == 200
            all_ok &= ok
            lines.append(f"  [{'OK' if ok else 'FAIL'}] GET /clients with auth -> {r.status_code}")
            if ok:
                r = httpx.post(f"{base}/clients", headers=headers, json={"name": "STAGING TEST - DELETE ME"}, timeout=5)
                created_ok = r.status_code == 201
                all_ok &= created_ok
                new_id = r.json().get("id") if created_ok else None
                lines.append(f"  [{'OK' if created_ok else 'FAIL'}] POST /clients (test record) -> {r.status_code}")
                if new_id is not None:
                    r = httpx.get(f"{base}/clients/{new_id}", headers=headers, timeout=5)
                    read_ok = r.status_code == 200
                    all_ok &= read_ok
                    lines.append(f"  [{'OK' if read_ok else 'FAIL'}] GET /clients/{{id}} (read back) -> {r.status_code}")
                    # No DELETE endpoint exists on this router -- clean up
                    # the test row directly, the same way a soft-delete
                    # migration tool would.
                    cleanup_engine = create_engine(canonical_url, future=True)
                    with cleanup_engine.begin() as conn:
                        conn.execute(text("DELETE FROM clients WHERE id = :id"), {"id": new_id})
                    lines.append(f"  [OK] cleaned up test record id={new_id} directly (no DELETE route exists)")
        else:
            lines.append("  [SKIP] authenticated CRUD test (no token provided)")

        return all_ok, lines
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        log_path.unlink(missing_ok=True)


def main() -> int:
    print("=" * 70)
    print("VINCO PostgreSQL staging verification")
    print("=" * 70)

    raw_url = get_database_url()
    parsed = build_engine_url(raw_url, STAGING_SCHEMA)
    canonical_url = parsed.render_as_string(hide_password=False)
    redact = make_redactor(raw_url, canonical_url, parsed.password or "", parsed.username or "")

    engine = create_engine(canonical_url, future=True)
    base_env = os.environ.copy()

    report: list[tuple[str, bool, str]] = []

    version = check_connection(engine, redact)
    report.append(("Connect to PostgreSQL", True, version))

    reset_staging_schema(engine, STAGING_SCHEMA)
    report.append((f"Isolated staging schema '{STAGING_SCHEMA}' ready (public untouched)", True, ""))

    ok, compat_output = run_compat_tests(canonical_url, base_env, redact)
    report.append(("PostgreSQL compatibility tests", ok, "" if ok else compat_output[-2000:]))
    if not ok:
        raise StagingCheckFailed("PostgreSQL compatibility tests failed -- see output above.")

    ok, migration_output = apply_baseline_migration(canonical_url, base_env, redact)
    report.append(("Apply baseline migration", ok, "" if ok else migration_output[-2000:]))
    if not ok:
        raise StagingCheckFailed("Baseline migration failed -- see output above.")

    print("[6/11] Locating and copying the real SQLite database...")
    original_path = locate_sqlite_db()
    original_hash_before = sha256_of(original_path)
    copy_path = make_copy(original_path)
    print(f"        Copied to {copy_path} (original untouched, checksum recorded)")
    report.append(("Copy real SQLite database", True, str(copy_path)))

    print("[7/11] Migrating the copy's data into PostgreSQL...")
    from app.database.migrate_sqlite_to_postgres import migrate as migrate_data

    rc = migrate_data(f"sqlite:///{copy_path}", canonical_url, dry_run=False, force=False)
    ok = rc == 0
    report.append(("Migrate SQLite copy -> PostgreSQL", ok, ""))
    if not ok:
        raise StagingCheckFailed("Data migration failed -- see output above.")

    print("[8/11] Verifying row counts, financial totals, foreign keys, sequences...")
    from app.database.verify_postgres_staging import (
        check_foreign_key_integrity,
        check_sequences,
        compare_financial_totals,
        compare_row_counts,
    )

    source_engine = create_engine(f"sqlite:///{copy_path}", future=True)
    ok_counts = compare_row_counts(source_engine, engine)
    ok_totals = compare_financial_totals(source_engine, engine)
    ok_fks = check_foreign_key_integrity(engine)
    ok_seqs = check_sequences(engine)
    report.append(("Row counts match", ok_counts, ""))
    report.append(("Financial totals match", ok_totals, ""))
    report.append(("Foreign key integrity", ok_fks, ""))
    report.append(("Sequence positions correct", ok_seqs, ""))

    ok, api_lines = run_api_smoke_tests(canonical_url, base_env, redact)
    report.append(("API smoke tests", ok, "\n".join(api_lines)))
    print("\n".join(api_lines))

    print("[10/11] Confirming the original SQLite database was not modified...")
    original_hash_after = sha256_of(original_path)
    sqlite_unchanged = original_hash_before == original_hash_after
    report.append(("Original SQLite database unchanged", sqlite_unchanged, ""))
    print("        " + ("UNCHANGED" if sqlite_unchanged else "!!! CHANGED !!!"))

    print("\n[11/11] Final report")
    print("=" * 70)
    all_passed = True
    for name, ok, detail in report:
        all_passed &= ok
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}")
        if detail and not ok:
            print(f"         {detail}")
    print("=" * 70)
    print("OVERALL: " + ("ALL CHECKS PASSED" if all_passed else "ONE OR MORE CHECKS FAILED"))
    print(f"Staged data lives in the isolated '{STAGING_SCHEMA}' schema only -- your public schema was never touched.")
    print(f"Test record cleanup: {'done' if any('cleaned up' in line for line in api_lines) else 'n/a (no token provided, no write test performed)'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StagingCheckFailed as e:
        print(f"\nABORTED: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        # Catch-all so an unexpected error can never dump a raw traceback
        # that might contain connection details. The specific redactor
        # built in main() isn't in scope here, so fall back to a generic
        # regex that strips credentials out of any URI-shaped substring
        # (scheme://user:password@host) before printing anything.
        last_line = _defensive_redact(traceback.format_exc().splitlines()[-1])
        print("\nUNEXPECTED ERROR -- aborting without printing full details for safety.", file=sys.stderr)
        print(last_line, file=sys.stderr)
        sys.exit(1)
