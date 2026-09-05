FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg[binary] and PyMuPDF wheels are unnecessary
# (both ship prebuilt wheels for linux/amd64) -- but the OCR fallback
# path (app/core/ocr_engine.py's TesseractOcrEngine, used when a
# scanned/image quotation has no extractable text) needs the real
# `tesseract` binary, which is not a Python package and was never
# installed here at all. Without it, `TesseractOcrEngine.is_available()`
# always returns False in production, so `app/core/ocr_extraction.py`'s
# `extract_via_ocr` always reports `requires_ocr=True` regardless of
# what's actually in the document -- every scanned PDF landed on
# ExtractionStatus.OCR_REQUIRED immediately, with no OCR ever actually
# attempted. `--no-install-recommends` keeps this from pulling in the
# full X11/desktop dependency chain some Tesseract packaging drags in;
# just the OCR engine and its English-language data.
RUN apt-get update && apt-get install --no-install-recommends -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# `.[ocr]` (not bare `.`) -- pyproject.toml deliberately keeps
# pytesseract/Pillow as an optional extra rather than a hard dependency
# (so a machine without Tesseract installed, e.g. this same image before
# this fix, still runs everything else correctly and just degrades OCR
# to "not available" -- see ocr_engine.py). That degrade-gracefully
# design means a plain `pip install .` here builds and runs a seemingly
# healthy API that can never actually OCR anything -- no import error,
# no crash, just OCR_REQUIRED on every scanned document forever. The
# system package installed above is necessary but not sufficient on its
# own; both halves have to be present for OCR to actually run.
RUN pip install --no-cache-dir ".[ocr]"

# Render (and most PaaS providers) inject $PORT at runtime; default to
# 8000 for local `docker run` / other hosts that don't set it.
ENV PORT=8000
EXPOSE 8000

# `app.database.migrate_production` runs `alembic upgrade head` (see
# that module's own docstring for the real production incident this
# fixes) and exits non-zero on any failure -- `&&` means a failed
# migration never reaches `exec uvicorn`, so this container never
# starts serving traffic against a schema its own code doesn't match.
# `exec` replaces this shell with the uvicorn process (not a child of
# it) so it receives SIGTERM/SIGINT directly from Render/Docker instead
# of the shell swallowing them. Only this CMD does this -- the worker
# service's `dockerCommand` (render.yaml) points straight at `python -m
# app.worker`, bypassing this file's CMD entirely, so exactly one
# process per deploy ever runs a migration.
CMD ["sh", "-c", "python -m app.database.migrate_production && exec uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}"]
