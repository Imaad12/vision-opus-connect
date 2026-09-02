"""Regression coverage for `scripts/safe_production_migrate.sh`'s
dependency bootstrap -- the exact real production incident this covers:
running the script on a normal checkout with no `backend/.venv` yet (or
one missing sqlalchemy/alembic/psycopg) failed with a bare
`ModuleNotFoundError: No module named 'sqlalchemy'` *before* any of the
script's destructive-migration safety checks ever ran.

These tests exercise the bootstrap logic in isolation, against a
throwaway copy of the script in its own temp directory -- never the real
`backend/.venv` (only ever *read* via a symlink, to prove the "already
bootstrapped" fast path skips reinstalling). A real from-scratch
`pip install -e .` (network/PySide6/pandas/PyMuPDF and friends) is
deliberately NOT exercised here -- slow and network-dependent, the same
tradeoff this codebase already makes elsewhere for exactly this reason
(see IMPORT_ARCHITECTURE.md on synthetic CI fixtures instead of real
archive PDFs). `test_batch_ingestion.py`-style "reproduce the real
failure directly" is instead achieved by controlling *which* `python3`
the script finds on PATH, not by skipping dependency installation
checks entirely.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_BACKEND = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_BACKEND / "scripts" / "safe_production_migrate.sh"
_REAL_VENV_PYTHON = _REPO_BACKEND / ".venv" / "bin" / "python3"


def test_script_is_valid_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def isolated_script(tmp_path: Path) -> Path:
    """A throwaway `backend/` directory: real `pyproject.toml`/
    `alembic.ini`/`migrations`/`app` (all read-only, symlinked from the
    actual repo -- needed for the script to get as far as attempting a
    real DB connection) plus its own disposable `scripts/` and `.venv/`,
    so a test can freely control what's "already installed" without
    touching the real `backend/.venv` this whole test suite itself runs
    from. `BACKEND_DIR`/`VENV_DIR` inside the script are computed from
    the script's own location, which is what makes this redirection
    work at all.
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
    return dest


def _run(script: Path, *, path_dirs: list[Path], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {
        "PATH": ":".join(str(p) for p in path_dirs),
        "HOME": str(script.parents[2]),  # keep pip/venv state inside tmp_path
        "VISION_DATABASE_URL": "postgresql+psycopg://baduser:badpass@127.0.0.1:1/doesnotexist",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env, timeout=60
    )


def test_refuses_clearly_when_only_an_older_python_is_available(isolated_script: Path, tmp_path: Path) -> None:
    """The exact scenario a fresh checkout can hit: a `python3` on PATH
    that isn't 3.12+ (this project's own `requires-python`). Must fail
    with a clear, specific message naming the requirement -- never a
    bare pip/ModuleNotFoundError traceback."""
    old_python = shutil.which("python3.11") or shutil.which("python3.10")
    if old_python is None:
        pytest.skip("no Python older than 3.12 available in this environment to test against")

    fake_path_dir = tmp_path / "fakebin"
    fake_path_dir.mkdir()
    (fake_path_dir / "python3").symlink_to(old_python)
    # Deliberately NOT the real /usr/bin wholesale -- that also contains
    # real python3.12/python3.13 binaries, which would defeat the whole
    # point of this test (find_system_python would just find those
    # instead). Only the specific coreutils the script actually needs.
    for tool in ("bash", "cat", "mktemp", "dirname", "rm"):
        src = shutil.which(tool)
        if src:
            (fake_path_dir / tool).symlink_to(src)

    result = _run(isolated_script, path_dirs=[fake_path_dir])

    assert result.returncode != 0
    assert "3.12" in result.stdout + result.stderr
    assert "ModuleNotFoundError" not in (result.stdout + result.stderr)


def test_refuses_clearly_when_no_python_is_available_at_all(isolated_script: Path, tmp_path: Path) -> None:
    fake_path_dir = tmp_path / "emptybin"
    fake_path_dir.mkdir()
    # Only non-python coreutils on PATH -- proves the "no python3 at
    # all" branch specifically, distinct from the "found one but it's
    # too old" branch the previous test covers.
    for tool in ("bash", "cat", "mktemp", "dirname", "rm"):
        src = shutil.which(tool)
        if src:
            (fake_path_dir / tool).symlink_to(src)

    result = _run(isolated_script, path_dirs=[fake_path_dir])

    assert result.returncode != 0
    assert "No python3 found" in (result.stdout + result.stderr)


@pytest.mark.skipif(not _REAL_VENV_PYTHON.exists(), reason="backend/.venv not set up in this environment")
def test_skips_reinstalling_when_dependencies_are_already_present(
    isolated_script: Path, tmp_path: Path
) -> None:
    """The fast path: an already-bootstrapped venv (this repo's own real
    one, only ever read via a symlink -- never modified) must not be
    reinstalled into, and the script must reach past the Python-import
    stage (a real DB connection attempt) rather than failing with
    ModuleNotFoundError -- the direct regression test for the reported
    production incident."""
    backend_dir = isolated_script.parents[1]
    # The whole directory, not individual files -- a venv's python3
    # locates its own site-packages via a `pyvenv.cfg` landmark file
    # sitting alongside `bin/`, so symlinking only `bin/python3` in
    # isolation would silently fail to be recognized as that venv at
    # all (and this test would pass for the wrong reason: falling back
    # to *some* system python that happens to lack these packages too).
    (backend_dir / ".venv").symlink_to(_REPO_BACKEND / ".venv")

    system_bin_dirs = [Path(p) for p in ("/usr/bin", "/bin") if Path(p).exists()]
    result = _run(isolated_script, path_dirs=system_bin_dirs)

    assert "[bootstrap] Installing" not in result.stdout
    assert "ModuleNotFoundError" not in (result.stdout + result.stderr)
    # Got past bootstrap and import all the way to a real connection
    # attempt against the (deliberately unreachable) VISION_DATABASE_URL.
    assert "Connection refused" in (result.stdout + result.stderr) or "OperationalError" in (
        result.stdout + result.stderr
    )
