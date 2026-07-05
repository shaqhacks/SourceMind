# SourceMind

SourceMind is a local-first course workbook generator for evidence-grounded study, retrieval practice, spaced review, and vertical knowledge transfer. Upload one or more course PDFs, approve the extracted chapter outline, and SourceMind generates a full verbose course book in the background — chapter by chapter, source-grounded, written in a Path-to-Staff style. Study each chapter in the built-in mdBook-style reader, track mastery with in-app spaced-repetition reviews, and export flashcards to Anki.

This repository is a monorepo:

- `backend/` — FastAPI API, pipeline services, DB models, and learning engines.
- `frontend/` — Next.js App Router frontend.
- `data/subjects/` — legacy local Markdown subject files (original subject workflow).
- `data/courses/` — legacy local Markdown course files (original course workbook workflow).

## New Pipeline

1. **Upload** — open `http://127.0.0.1:3000/upload` and drop one or more ordered PDFs for a course.
2. **Review plan** — SourceMind extracts a chapter/section outline and presents it for review. Edit titles or reorder sections as needed.
3. **Approve** — confirm the plan to kick off background generation.
4. **Generate** — chapters are generated one at a time in the background. Each chapter is verbose, source-grounded, and written in a Path-to-Staff pedagogical style (motivation → concept → worked examples → understanding checks → mastery quiz).
5. **Read** — browse the generated course in the mdBook-style reader. Each chapter includes objectives, teaching blocks, worked examples, comprehension checks, and a tutor chat.
6. **Review** — open `http://127.0.0.1:3000/reviews/due` for spaced-repetition review of material that is coming due. Export any chapter's importance cards to Anki via the `.tsv` download link.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SOURCEMIND_LLM_PROVIDER` | `claude` | LLM backend — `claude` (Anthropic) or `ollama` (local). |
| `SOURCEMIND_LLM_MODEL` | provider default | Override the model name (e.g. `claude-opus-4-5` or `llama3.1`). |
| `ANTHROPIC_API_KEY` | — | Required when `SOURCEMIND_LLM_PROVIDER=claude`. |
| `SOURCEMIND_DB_URL` | `sqlite:///data/sourcemind.db` | SQLAlchemy DB URL. Defaults to a local SQLite file. |
| `SOURCEMIND_ASSETS_DIR` | `data/` | Directory for uploaded PDFs and extracted assets. |
| `SOURCEMIND_CORS_ORIGINS` | — | Comma-separated additional CORS origins (localhost:3000 is always allowed). |

## Run Locally

Start the backend and frontend together:

```bash
./scripts/dev.sh
```

The frontend runs at `http://127.0.0.1:3000` and the API at `http://127.0.0.1:8000`.
Press `Ctrl+C` to stop both processes.

Override port or provider:

```bash
BACKEND_PORT=8001 FRONTEND_PORT=3001 ./scripts/dev.sh
SOURCEMIND_LLM_PROVIDER=ollama SOURCEMIND_LLM_MODEL=llama3.2 ./scripts/dev.sh
```

## Build and Test

Run the full local verification path (compile backend, run test suite, build frontend):

```bash
./scripts/build.sh
```

Run only the backend tests:

```bash
uv run pytest backend/tests
```

## Database

The backend auto-creates its SQLite schema on startup (`init_db()` runs via the FastAPI lifespan hook). No manual migration step is required for a fresh checkout.

The `data/sourcemind.db` file is listed in `.gitignore` and is never committed. Tests redirect the DB to a temporary path automatically — no stray DB file is written during `uv run pytest`.

## Legacy Data

The original `/courses`, `/subjects`, and competency-decomposition endpoints have been removed — the `/library` flow described above is the only API surface (`backend/routers/library.py`). The `data/subjects/` and `data/courses/` Markdown files from the original workflow are no longer read by the backend; the entire `data/` directory is runtime storage and is not versioned.

## For Contributors (human or agent)

- [`CLAUDE.md`](CLAUDE.md) — working agreements and hard invariants. Read before changing code.
- [`docs/architecture.md`](docs/architecture.md) — system map, course lifecycle, data contracts, failure model.
- [`docs/decisions.md`](docs/decisions.md) — decision records with the reasoning; append a new entry when you make a call future maintainers could second-guess.

## Product Drafts

- [SourceMind first draft](docs/sourcemind-first-draft.md): evidence-backed lesson engine thesis, method rationale, lesson model, and implementation game plan.
