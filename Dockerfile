FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY arkpg ./arkpg
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --upgrade pip && pip install .

CMD ["python", "-m", "arkpg.main"]
