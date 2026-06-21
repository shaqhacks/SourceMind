# SourceMind

SourceMind is a local-first course workbook generator for evidence-grounded study, retrieval practice, spaced review, and vertical knowledge transfer. Students can upload one or more course PDFs, approve the extracted outline, generate a full course book in the background, study each lesson with a tutor chat, and revisit material when it becomes due.

This repository is scaffolded as a monorepo:

- `backend/`: FastAPI services and learning engines.
- `frontend/`: Next.js App Router frontend.
- `data/subjects/`: legacy local Markdown subject files used by the original subject workflow.
- `data/courses/`: local Markdown course files used by the course workbook workflow.

## Build

Run the full local verification path:

```bash
./scripts/build.sh
```

The build script compiles the backend, runs the backend test suite with `uv`-managed Python dependencies, and builds the Next.js frontend.

## Run Locally

Start the backend and frontend together:

```bash
./scripts/dev.sh
```

The app runs at `http://127.0.0.1:3000` and the API runs at `http://127.0.0.1:8000`. Press `Ctrl+C` in the terminal to stop both processes.

Optional overrides:

```bash
BACKEND_PORT=8001 FRONTEND_PORT=3001 ./scripts/dev.sh
```

## Course Workflow

1. Open `http://127.0.0.1:3000/upload`.
2. Upload one or more ordered PDFs for the same course.
3. Review and approve the extracted chapter/section outline.
4. Start generation. Lessons are generated in the background with progress and retry status.
5. Study lessons from the course page. Each lesson includes objectives, teaching blocks, worked examples, understanding checks, a mastery quiz, competency progress, and tutor chat.
6. Open `http://127.0.0.1:3000/reviews/due` to see material scheduled for review.

Review scheduling is driven by score and confidence. High-confidence misses are due immediately; passing work is spaced out over later review intervals. The dashboard shows a due-review notification count.

## Local Model

Course generation and tutor chat use Ollama through the backend. By default the backend asks for `llama3.1`; override it with:

```bash
OLLAMA_MODEL=llama3.2 ./scripts/dev.sh
```

For development-only deterministic lesson generation without Ollama:

```bash
SOURCEMIND_ALLOW_DETERMINISTIC_GENERATION=1 ./scripts/dev.sh
```

## Product Drafts

- [SourceMind first draft](docs/sourcemind-first-draft.md): evidence-backed lesson engine thesis, method rationale, lesson model, and implementation game plan.
