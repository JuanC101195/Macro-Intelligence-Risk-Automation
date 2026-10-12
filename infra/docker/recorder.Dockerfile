# Macro snapshot recorder (trading-system macro record). No MT5: Linux only needs Crucix.
#
# Supply-chain hardening:
# - dependencies come from a lock file with pinned versions AND hashes (--require-hashes);
# - only prebuilt wheels are accepted (--only-binary :all:), so no setup scripts run;
# - our own code is copied, not built/installed, and run via PYTHONPATH.
# uv.lock is the single source of truth. After changing dependencies in pyproject.toml:
#   uv lock
#   uv export --frozen --no-emit-project --no-dev --format requirements-txt \
#     --output-file infra/docker/requirements.lock
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY infra/docker/requirements.lock /tmp/requirements.lock
RUN pip install --only-binary :all: --require-hashes --no-deps -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock

COPY src ./src

# uid 1000 = the host user that owns the bind-mounted data dir (azureuser on Ubuntu).
RUN useradd --create-home --uid 1000 itp \
    && mkdir -p /data/macro_snapshots \
    && chown -R itp /data

USER itp
WORKDIR /home/itp
VOLUME ["/data/macro_snapshots"]

ENTRYPOINT ["python", "-m", "trading_system.cli"]
CMD ["macro", "record", "--interval-minutes", "15", "--wait-minutes", "10", \
     "--out", "/data/macro_snapshots"]
