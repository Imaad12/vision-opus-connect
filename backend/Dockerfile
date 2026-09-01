FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg[binary] and PyMuPDF wheels are unnecessary
# (both ship prebuilt wheels for linux/amd64), so no build-essential here.

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN pip install --no-cache-dir .

# Render (and most PaaS providers) inject $PORT at runtime; default to
# 8000 for local `docker run` / other hosts that don't set it.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}"]
