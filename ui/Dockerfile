FROM python:3.12-slim
# Install Debian's security fixes now, instead of waiting for the official image to be rebuilt.
# The dependency scan (.github/workflows/dependency-scan.yml) checks the result.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
