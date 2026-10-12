# Macro snapshot recorder (trading-system macro record). No MT5: Linux only needs Crucix.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
    && useradd --create-home --uid 10001 itp \
    && mkdir -p /data/macro_snapshots \
    && chown -R itp /data

USER itp
WORKDIR /home/itp
VOLUME ["/data/macro_snapshots"]

ENTRYPOINT ["trading-system"]
CMD ["macro", "record", "--interval-minutes", "15", "--wait-minutes", "10", \
     "--out", "/data/macro_snapshots"]
