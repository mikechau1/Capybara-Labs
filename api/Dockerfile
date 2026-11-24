FROM python:3.12-slim
# Install Debian's security fixes now, instead of waiting for the official image to be rebuilt.
# The dependency scan (.github/workflows/dependency-scan.yml) checks the result.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
