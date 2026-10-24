# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage — compiles any sdist-only deps, then throws the toolchain away.
# Was python:3.11-alpine, which uses musl and therefore has no manylinux wheels:
# every C extension was compiled from source on each build.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
# Only the manifest, so this layer stays cached across code changes. The build
# resolves to an empty distribution (tgbot/ is not copied here) — deliberate:
# we want the venv to hold dependencies only, while the application itself is
# run from /app in the runtime stage.
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

# ---------------------------------------------------------------------------
# Runtime stage — no compiler, no apt lists, non-root.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=10001:10001 . .

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 80

# No wait-for-postgres loop here any more: compose gates startup on the
# postgres healthcheck and on the migrations job completing. The old CMD also
# shelled out to `nc`, which does not exist in slim.
CMD ["python", "bot.py"]
