"""Regression coverage for `scripts/safe_production_migrate.sh`'s
dependency bootstrap.

Two real, distinct production incidents this covers:

1. A fresh checkout with no `backend/.venv` yet failed outright with a
   bare `ModuleNotFoundError: No module named 'sqlalchemy'` *before* any
   of the script's destructive-migration safety checks ever ran (no
   bootstrap logic existed at all).
2. After adding bootstrap logic, a real macOS run still selected a
   Python 3.9.6 interpreter, got as far as `pip install -e .` (which
   correctly refused it: "requires a different Python: 3.9.6 not in
   '>=3.12'"), and the script *continued anyway* -- prompting for
   VISION_DATABASE_URL and only failing later with
   `ModuleNotFoundError: No module named 'alembic'`. Two independent
   bugs, both covered here: (a) whatever put a sub-3.12 interpreter in
   front of a valid one on that machine, and (b) the script not
   checking `pip install`'s own exit code at all.

Every test drives the REAL script (never a reimplementation or a mock of
its logic) against a disposable, fully isolated `backend/` directory --
`pyproject.toml`/`alembic.ini`/`migrations`/`app` symlinked read-only
from the real repo (needed to reach a real DB-connection attempt), a
tightly controlled `PATH` so each test decides exactly which `python3*`
names exist and what they actually are, and its own `.venv`/`HOME` so
nothing here ever reads or writes the real `backend/.venv` this suite
itself runs from. A real from-scratch `pip install -e .` of this
project's full dependency list (network, PySide6/pandas/PyMuPDF) is
deliberately not exercised -- slow and network-dependent, the same
tradeoff this codebase already makes elsewhere (see
IMPORT_ARCHITECTURE.md on synthetic CI fixtures instead of real archive
PDFs) -- the "3.12 accepted" and "install failure" cases below instead
use a REAL local Python 3.12+ interpreter with a disposable, minimal, or
deliberately-broken `pyproject.toml`, which is enough to prove the
script's own decision logic without a slow, network-dependent full
install.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_BACKEND = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_BACKEND / "scripts" / "safe_production_migrate.sh"
_REAL_VENV_PYTHON = _REPO_BACKEND / ".venv" / "bin" / "python3"
_COREUTILS = ("bash", "cat", "mktemp", "dirname", "rm")


def test_script_is_valid_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _make_fake_bin(base: Path, name: str, extra_tools: tuple[str, ...] = ()) -> Path:
    """A PATH directory containing only the named tools (as real symlinks)
    -- never the real /usr/bin wholesale, which would also expose real
    python3.12/python3.13 binaries and defeat the whole point of a test
    that controls exactly what Python versions are "available"."""
    fake = base / name
    fake.mkdir()
    for tool in (*_COREUTILS, *extra_tools):
        src = shutil.which(tool)
        if src:
            (fake / tool).symlink_to(src)
    return fake


@pytest.fixture
def isolated_backend(tmp_path: Path) -> Path:
    """A throwaway `backend/` directory: real `pyproject.toml`/
    `alembic.ini`/`migrations`/`app` (symlinked read-only from the actual
    repo -- needed for the script to get as far as a real DB connection
    attempt) plus its own disposable `scripts/`, with no `.venv` yet.
    `BACKEND_DIR`/`VENV_DIR` inside the script are computed from the
    script's own location, which is what makes this redirection work.
    """
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    for name in ("pyproject.toml", "alembic.ini", "migrations", "app"):
        (backend_dir / name).symlink_to(_REPO_BACKEND / name)
    scripts_dir = backend_dir / "scripts"
    scripts_dir.mkdir()
    dest = scripts_dir / "safe_production_migrate.sh"
    shutil.copy(_SCRIPT, dest)
    dest.chmod(0o755)
    return backend_dir


@pytest.fixture
def isolated_backend_minimal(tmp_path: Path) -> Path:
    """Like `isolated_backend`, but with a real, minimal `pyproject.toml`
    declaring only the three packages `dependencies_importable` (in the
    script) actually checks for (sqlalchemy/alembic/psycopg), not this
    repo's own full, much heavier dependency list (PySide6/pandas/
    PyMuPDF/...) -- for tests that need `pip install -e .` to actually
    SUCCEED quickly, proving the script's own bootstrap-success path
    end-to-end without that slow, unnecessary full install (see module
    docstring). Still symlinks the real `app`/`alembic.ini`/`migrations`
    (like `isolated_backend`) so the script's Python heredoc can actually
    `import app...` and reach a real DB-connection attempt afterward --
    without this, the heredoc fails immediately with `ModuleNotFoundError:
    No module named 'app'`, which looks like a bootstrap failure but
    actually only proves bootstrap succeeded and the script moved on to
    its next stage; that's not what these tests are checking.
    """
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "pyproject.toml").write_text(
        "[project]\n"
        'name = "minimal-fake-backend"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        "dependencies = [\n"
        '    "SQLAlchemy>=2.0,<3.0",\n'
        '    "alembic>=1.13,<2.0",\n'
        '    "psycopg[binary]>=3.1,<4.0",\n'
        # Not checked by `dependencies_importable`, but `app.core.config`
        # (imported by the script's own heredoc, transitively via `from
        # app.core.config import ...`) needs it to import at all --
        # without this the heredoc fails at that import, before ever
        # reaching a DB-connection attempt.
        '    "pydantic-settings>=2.2,<3.0",\n'
        "]\n"
        "\n"
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n"
        "[tool.setuptools.packages.find]\n"
        'include = ["app*"]\n'
    )
    for name in ("alembic.ini", "migrations", "app"):
        (backend_dir / name).symlink_to(_REPO_BACKEND / name)
    scripts_dir = backend_dir / "scripts"
    scripts_dir.mkdir()
    dest = scripts_dir / "safe_production_migrate.sh"
    shutil.copy(_SCRIPT, dest)
    dest.chmod(0o755)
    return backend_dir


def _script(backend_dir: Path) -> Path:
    return backend_dir / "scripts" / "safe_production_migrate.sh"


def _run(
    backend_dir: Path,
    *,
    path_dirs: list[Path],
    set_database_url: bool = True,
    stdin_devnull: bool = False,
) -> subprocess.CompletedProcess:
    env = {"PATH": ":".join(str(p) for p in path_dirs), "HOME": str(backend_dir.parent)}
    if set_database_url:
        env["VISION_DATABASE_URL"] = "postgresql+psycopg://baduser:badpass@127.0.0.1:1/doesnotexist"
    return subprocess.run(
        ["bash", str(_script(backend_dir))],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
        stdin=subprocess.DEVNULL if stdin_devnull else None,
    )


# --- Python version selection -----------------------------------------------


def test_rejects_an_old_python_like_3_9(isolated_backend: Path, tmp_path: Path) -> None:
    """Stands in for the real macOS report (system Python 3.9.6): any
    Python older than the required 3.12 on PATH, named plain `python3`,
    must be refused with a clear message -- never silently used to
    create a venv."""
    old_python = shutil.which("python3.11") or shutil.which("python3.10") or shutil.which("python3.9")
    if old_python is None:
        pytest.skip("no Python older than 3.12 available in this environment to test against")

    fake_bin = _make_fake_bin(tmp_path, "oldbin")
    (fake_bin / "python3").symlink_to(old_python)

    result = _run(isolated_backend, path_dirs=[fake_bin])

    assert result.returncode != 0
    assert "3.12" in result.stdout + result.stderr
    assert "ModuleNotFoundError" not in (result.stdout + result.stderr)
    assert not (isolated_backend / ".venv").exists(), "must not create a venv from a rejected interpreter"


def test_rejects_a_python3_12_named_binary_that_is_actually_old(
    isolated_backend: Path, tmp_path: Path
) -> None:
    """The scenario the original per-candidate design missed: a command
    literally named `python3.12` exists on PATH (a stale shim, a
    misconfigured version manager, an unrelated alias) but its ACTUAL
    reported version is older than 3.12. Must be rejected by its real
    version, never trusted by name -- and, since no other valid
    candidate exists here either, must fall through to the same clear
    refusal as no-python-found."""
    old_python = shutil.which("python3.11") or shutil.which("python3.10")
    if old_python is None:
        pytest.skip("no Python older than 3.12 available in this environment to test against")

    fake_bin = _make_fake_bin(tmp_path, "shimbin")
    (fake_bin / "python3.12").symlink_to(old_python)  # name lies about its version

    result = _run(isolated_backend, path_dirs=[fake_bin])

    assert result.returncode != 0
    assert "ModuleNotFoundError" not in (result.stdout + result.stderr)
    assert not (isolated_backend / ".venv").exists()


def test_rejects_when_no_python3_is_available_at_all(isolated_backend: Path, tmp_path: Path) -> None:
    fake_bin = _make_fake_bin(tmp_path, "emptybin")

    result = _run(isolated_backend, path_dirs=[fake_bin])

    assert result.returncode != 0
    assert "No Python 3.12+ found" in (result.stdout + result.stderr)


def test_accepts_a_real_python_3_12_or_newer(isolated_backend_minimal: Path, tmp_path: Path) -> None:
    """The positive case: when a genuinely valid interpreter is on PATH
    (by name AND by actual version), the script must select it, create
    a venv with it, and successfully install into it (a trivial,
    dependency-free real package -- see `isolated_backend_minimal` --
    so this completes quickly and offline, unlike this project's own
    real, heavy dependency list)."""
    valid_python = shutil.which("python3.12") or shutil.which("python3.13")
    if valid_python is None:
        pytest.skip("no real Python 3.12+ available in this environment to test against")

    fake_bin = _make_fake_bin(tmp_path, "validbin")
    (fake_bin / "python3.12").symlink_to(valid_python)

    result = _run(isolated_backend_minimal, path_dirs=[fake_bin])

    assert "[UNSAFE]" not in result.stderr
    assert (isolated_backend_minimal / ".venv" / "bin" / "python3").exists()
    assert "[bootstrap] Creating virtual environment" in result.stdout
    assert "Python 3.12" in result.stdout or "Python 3.13" in result.stdout
    assert "[bootstrap] Installing backend dependencies" in result.stdout
    # Got all the way past bootstrap to a real DB connection attempt
    # against the deliberately-unreachable VISION_DATABASE_URL (same
    # signal `test_skips_reinstalling_when_dependencies_are_already_
    # present` uses) -- this fixture has no alembic.ini/migrations/app,
    # but those are only read *after* a successful connection, which
    # this garbage URL never reaches.
    assert "Connection refused" in result.stderr or "OperationalError" in result.stderr


# --- Stale/broken existing venv ---------------------------------------------


def test_rebuilds_a_stale_venv_left_by_an_old_python(
    isolated_backend_minimal: Path, tmp_path: Path
) -> None:
    """Direct regression test for the second half of the real incident:
    once a sub-3.12 venv exists (from a prior failed run), a re-run must
    detect and remove it -- not keep reusing it (which is exactly how
    the real run reached `ModuleNotFoundError: No module named
    'alembic'`: pip install into the bad venv had already failed, but
    the script kept using that same broken venv on top of the
    unchecked-exit-code bug)."""
    old_python = shutil.which("python3.11") or shutil.which("python3.10")
    valid_python = shutil.which("python3.12") or shutil.which("python3.13")
    if old_python is None or valid_python is None:
        pytest.skip("need both an old and a valid Python available in this environment")

    stale_venv = isolated_backend_minimal / ".venv"
    subprocess.run([old_python, "-m", "venv", str(stale_venv)], check=True, capture_output=True)
    assert (stale_venv / "bin" / "python3").exists()

    fake_bin = _make_fake_bin(tmp_path, "rebuildbin")
    (fake_bin / "python3.12").symlink_to(valid_python)

    result = _run(isolated_backend_minimal, path_dirs=[fake_bin])

    assert "removing it and rebuilding" in result.stdout
    assert "[UNSAFE]" not in result.stderr
    # Actually completed a fresh, successful bootstrap afterward -- not
    # just removed the bad venv and stopped.
    assert "[bootstrap] Installing backend dependencies" in result.stdout
    assert "Connection refused" in result.stderr or "OperationalError" in result.stderr
    new_venv_python = stale_venv / "bin" / "python3"
    assert new_venv_python.exists()
    version_check = subprocess.run(
        [str(new_venv_python), "-c", "import sys; print(sys.version_info[:2] >= (3, 12))"],
        capture_output=True,
        text=True,
    )
    assert version_check.stdout.strip() == "True"


# --- Fail-closed dependency install ------------------------------------------


def test_failed_dependency_install_exits_immediately_before_the_database_prompt(
    isolated_backend: Path, tmp_path: Path
) -> None:
    """A real, offline, deterministic install failure -- an impossible
    `requires-python` on the local package itself (no network needed to
    fail; pip rejects it immediately, exactly the same shape of error
    the real incident hit: "requires a different Python"). Must exit
    nonzero right there, and never reach the VISION_DATABASE_URL prompt
    or any later safety-check stage."""
    valid_python = shutil.which("python3.12") or shutil.which("python3.13")
    if valid_python is None:
        pytest.skip("no real Python 3.12+ available in this environment to test against")

    # Replace the symlinked pyproject.toml with a real file pip cannot
    # possibly satisfy -- breaks `pip install -e .` itself, offline.
    (isolated_backend / "pyproject.toml").unlink()
    (isolated_backend / "pyproject.toml").write_text(
        "[project]\n"
        'name = "impossible-to-install"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=99.0"\n'
        "dependencies = []\n"
        "\n"
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n'
    )

    fake_bin = _make_fake_bin(tmp_path, "failbin")
    (fake_bin / "python3.12").symlink_to(valid_python)

    result = _run(isolated_backend, path_dirs=[fake_bin], set_database_url=False, stdin_devnull=True)

    assert result.returncode != 0
    assert "[UNSAFE]" in result.stderr
    assert "pip install -e . failed" in result.stderr or "'pip install -e .' failed" in result.stderr
    assert "Paste VISION_DATABASE_URL" not in result.stderr
    assert "Safety checks FAILED" not in result.stdout  # never reached that stage either


def test_no_database_prompt_occurs_after_bootstrap_failure(isolated_backend: Path, tmp_path: Path) -> None:
    """Same guarantee as above, isolated specifically to the
    no-valid-python case: with VISION_DATABASE_URL deliberately unset and
    stdin closed (so a `read` that *did* get reached would either hang --
    caught by the timeout -- or silently return empty, not this
    assertion), the script must exit on the Python-version check alone
    and never print or reach the prompt."""
    fake_bin = _make_fake_bin(tmp_path, "noprompt")

    result = _run(isolated_backend, path_dirs=[fake_bin], set_database_url=False, stdin_devnull=True)

    assert result.returncode != 0
    assert "No Python 3.12+ found" in result.stderr
    assert "Paste VISION_DATABASE_URL" not in result.stdout + result.stderr


# --- Already-bootstrapped fast path ------------------------------------------


@pytest.mark.skipif(not _REAL_VENV_PYTHON.exists(), reason="backend/.venv not set up in this environment")
def test_skips_reinstalling_when_dependencies_are_already_present(
    isolated_backend: Path, tmp_path: Path
) -> None:
    """The fast path: an already-bootstrapped, correctly-versioned venv
    (this repo's own real one, only ever *read* via a symlink -- never
    modified) must not be reinstalled into, and the script must reach
    past the Python-import stage to a real DB connection attempt rather
    than failing with ModuleNotFoundError."""
    # The whole directory, not individual files -- a venv's python3
    # locates its own site-packages via a `pyvenv.cfg` landmark file
    # sitting alongside `bin/`, so symlinking only `bin/python3` in
    # isolation would silently fail to be recognized as that venv at
    # all (and this test would pass for the wrong reason).
    (isolated_backend / ".venv").symlink_to(_REPO_BACKEND / ".venv")

    system_bin_dirs = [Path(p) for p in ("/usr/bin", "/bin") if Path(p).exists()]
    result = _run(isolated_backend, path_dirs=system_bin_dirs)

    assert "[bootstrap] Installing" not in result.stdout
    assert "ModuleNotFoundError" not in (result.stdout + result.stderr)
    assert "Connection refused" in (result.stdout + result.stderr) or "OperationalError" in (
        result.stdout + result.stderr
    )
