# Multi-arch base: works on Raspberry Pi (arm64) and dev machines (amd64).
FROM python:3.12-slim

# Don't buffer stdout/stderr so logs show up immediately in `docker compose logs`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application.
COPY main.py ./
COPY aurorahue ./aurorahue
COPY alembic.ini ./
COPY migrations ./migrations

# Run as a non-root user.
RUN useradd --create-home --uid 1000 app \
    && chown -R app:app /app
USER app

CMD ["python", "main.py"]
