# Embeddings

Card M2-03. Code: `api/app/shared/embeddings.py`.

Ingestion (M2-04) turns each chunk of text into a vector of 384 numbers, and retrieval (M2-07) turns each question into one too. Chunks whose vectors are closest to the question's are the best matches. Both must use the same model, or the numbers are not comparable.

## The model

| | |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2`, pinned to Hub revision `1110a243fdf4…` (`MODEL_REVISION`) |
| Runs on | CPU, inside the `api` container; no API key, no network at run time |
| Vector size | 384, unit length (so cosine similarity = dot product) |
| Input limit | 254 word pieces (256 minus two marker tokens), about 190 English words. Longer input is cut off and a warning is logged. The model was trained on shorter texts (128), so chunks of roughly 100–200 words work best. `count_tokens()` measures a chunk |
| Memory | About 450 MB once loaded (most of it is PyTorch itself), peaking around 700–860 MB while embedding a batch of 100 full-length chunks. At most 2 embeds run at once (more are no faster on a CPU, and 40 simultaneous ones reached 3.2 GB in review); with that limit, 8 simultaneous callers peaked at 653 MB. Loaded once per API process, on first use; simultaneous first requests share one load. Each extra uvicorn worker loads its own copy. Give the API container at least 1 GB (card M5-02) |
| Speed | About 5 s to load (the first request waits for it); 60–80 chunks/s for ~170-word chunks and 7–8 ms per question, on a laptop CPU (measured twice in the container, 2026-11-22) |
| Image size | The `api` image grows to about 2.4 GB: CPU-only PyTorch ~1 GB, transformers/scipy/scikit-learn ~0.6 GB, the model ~0.1 GB. No GPU libraries |

The model is downloaded while the Docker image is built (`api/Dockerfile`), and the container is told never to download at run time (`HF_HUB_OFFLINE=1`).

Which model made a vector matters: `embedder.model_id` (`…all-MiniLM-L6-v2@1110a243fdf4` or `fake-v2`) is stored with every chunk, so vectors from different embedders never get compared.

## Choosing the embedder

`EMBEDDER` in `.env`:

- `local` (default): the real model. Needs PyTorch, which the Docker image has.
- `fake`: deterministic word-hashing vectors. Texts sharing words come out close, but it understands no meaning. Tests always use it. To run the API outside Docker without PyTorch, set it in your shell (`EMBEDDER=fake uvicorn ...`, as in the README): `.env` is read only by Docker Compose, and putting `EMBEDDER=fake` there would quietly make the Docker API use the fake. The API logs `embedder ready` with the `model_id` when it starts embedding, and refuses `fake` when `ENVIRONMENT=production`.

## Running the real model outside Docker

PyTorch is large, so it is an optional extra rather than a normal dependency. In `api/`:

```bash
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu   # CPU-only, much smaller
pip install -e ".[embeddings]"
```

Without it, `pytest` still runs everything and skips the tests that need the real model. Tests always use the fake embedder unless they ask for the real one (`tests/conftest.py`). CI installs only `.[dev]`, so the real-model tests run only inside the image:

```bash
docker compose build api
docker run --rm -v "$PWD/api/tests:/srv/tests:ro" --entrypoint sh capybara-labs-api   -c "pip install -q pytest==9.2.0 httpx2==2.16.2 && python -m pytest -q tests/test_embeddings.py"
```

## Changing the model or its packages later

Every package in the image is pinned in `api/requirements-lock.txt` (including everything the model pulls in, such as `regex` and `safetensors`, which affect tokenizing and loading), and the base image is pinned by digest. The Dockerfile installs exactly the lock (`--no-deps`) and runs `pip check`. The `embeddings` extra in `api/pyproject.toml`, for installs outside Docker, must use the same versions (a test checks). `api/requirements-lock.txt` explains how to regenerate it. A golden-vector test (inside the image) fails if anything changes the model's output.

A new model or revision changes every vector: update `MODEL_REVISION` in `api/app/shared/embeddings.py` and the `MODEL_REVISION` build argument in `api/Dockerfile` together, then re-embed every chunk. A different vector size also needs a migration changing `chunks.embedding` (card M2-01) and `EMBEDDING_DIMENSIONS` in both places.

## Open questions for later cards

- CI does not build the API image (2.4 GB) or run the real model; decide in M1-08/M5-02 whether it should, e.g. only on changes to `api/Dockerfile` or `requirements-lock.txt`.
- Load the model when the API starts instead of on the first request? Avoids a 5 s wait for the first user but costs 450 MB even when idle (M2-07/M5-03).
- PyTorch uses as many threads as the machine has cores; cap it with `torch.set_num_threads` if the container gets a CPU limit (M5-02).
- Call `embed()` only from normal `def` routes or a worker thread, never directly inside `async def`, or it blocks every other request while it runs.
