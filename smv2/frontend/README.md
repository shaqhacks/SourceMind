# SourceMind frontend

Next.js (App Router) + TypeScript + Tailwind v4 client for SourceMind — the
reader, upload flow, dashboard, spaced-repetition review, and quiz surfaces.
No separate state library; each surface owns its own fetch/state via hooks
in `lib/hooks/`. See the root `CLAUDE.md` for the project's working
agreements and `AGENTS.md` (this directory) for Next.js version-specific
notes worth reading before touching routing/config.

## Generated API client

`lib/api/schema.d.ts` is generated from the backend's OpenAPI schema
(`../openapi.json`) via `npm run gen:api`, and is a committed artifact —
regenerate it after any backend schema change, don't hand-edit it. Every
request goes through `lib/api/client.ts`, which wraps `openapi-fetch` calls
into the `ApiResult<T>` pattern (`{data?, error?, status?, ok}` — helpers
never throw).

## Scripts

```bash
npm run dev        # dev server on :3000
npm run gen:api     # regenerate lib/api/schema.d.ts from ../openapi.json
npm run typecheck   # tsc --noEmit
npm test            # vitest
npm run lint        # eslint
npm run build       # production build (also type-checks)
```

`../build.sh` runs the full gate (backend + this frontend) — CI mirrors it
exactly, so `npm test -- --run && npm run build` locally is the fastest way
to reproduce a CI failure.
