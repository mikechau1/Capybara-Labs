# Base image pinned by digest, so a rebuild can't pick up a different Python or system libraries.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

WORKDIR /srv

# Every package at an exact version (requirements-lock.txt), installed exactly as listed and
# nothing else (--no-deps), then checked. torch comes from the CPU-only index: the default
# package adds gigabytes of GPU libraries that are never used here. Changing pyproject.toml
# alone doesn't reinstall these layers or re-download the model (card M2-03).
COPY requirements-lock.txt .
RUN pip install --no-cache-dir --no-deps -r requirements-lock.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip check

# Download the model now, at an exact revision, so the API never downloads at run time and
# every build produces the same vectors. Must match MODEL_REVISION in app/shared/embeddings.py
# (tests/test_embeddings.py checks).
ENV HF_HOME=/srv/models \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TQDM_DISABLE=1 \
    TRANSFORMERS_VERBOSITY=error
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41')"
ENV HF_HUB_OFFLINE=1

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
