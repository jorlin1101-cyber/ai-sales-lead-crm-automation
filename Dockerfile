FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY deploy/docker-entrypoint.sh ./deploy/docker-entrypoint.sh

RUN python -m pip install --constraint requirements.txt .

COPY data/demo/lead_feature_fixtures.json ./data/demo/lead_feature_fixtures.json
COPY data/knowledge_snapshot/knowledge_chunks.json ./data/knowledge_snapshot/knowledge_chunks.json
COPY data/knowledge_snapshot/translations.zh.json ./data/knowledge_snapshot/translations.zh.json

RUN addgroup --system app \
    && adduser --system --ingroup app app

RUN mkdir -p /app/data/runtime && chown app:app /app/data/runtime

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["/bin/sh", "/app/deploy/docker-entrypoint.sh"]
