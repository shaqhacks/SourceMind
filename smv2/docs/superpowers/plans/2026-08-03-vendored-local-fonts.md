# Vendored Local Fonts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frontend production build independent of Google Fonts network access while preserving Caprasimo, Figtree, Geist Mono, and the existing CSS variable contract.

**Architecture:** Vendor the official Latin WOFF2 files beside the App Router root layout and load them with `next/font/local`. The real regression boundary is the Next.js production build: it fails while `next/font/google` requires outbound access and passes after the local assets are wired in. Binary validation independently proves that each downloaded asset is a non-empty WOFF2 file.

**Tech Stack:** Next.js 16, TypeScript, `next/font/local`, official Google Fonts CSS distribution.

## Global Constraints

- Preserve `--font-caprasimo`, `--font-figtree`, and `--font-geist-mono` exactly.
- Preserve Caprasimo weight `400`, Figtree weight range `300 900`, and Geist Mono weight range `100 900`.
- Vendor only the Latin WOFF2 subset; do not add other language subsets.
- Add no runtime font request, package dependency, install script, or fallback-font redesign.
- Download only from the official `fonts.gstatic.com` URLs resolved by the Google Fonts CSS API, and preserve each family's OFL license from the official `google/fonts` repository.
- Preserve unrelated working-tree changes and do not create a commit unless the user explicitly requests one.

---

## File Structure

- Create `frontend/app/fonts/caprasimo-latin-400.woff2`: official Caprasimo v6 Latin subset.
- Create `frontend/app/fonts/figtree-latin-variable.woff2`: official Figtree v9 Latin variable subset for weights 300–900.
- Create `frontend/app/fonts/geist-mono-latin-variable.woff2`: official Geist Mono v6 Latin variable subset for weights 100–900.
- Create `frontend/app/fonts/licenses/Caprasimo-OFL.txt`: Caprasimo license from the official Google Fonts repository.
- Create `frontend/app/fonts/licenses/Figtree-OFL.txt`: Figtree license from the official Google Fonts repository.
- Create `frontend/app/fonts/licenses/Geist-Mono-OFL.txt`: Geist Mono license from the official Google Fonts repository.
- Create `frontend/app/fonts/README.md`: asset provenance, family metadata, and update procedure.
- Modify `frontend/app/layout.tsx`: replace `next/font/google` functions with three `next/font/local` declarations.

### Task 1: Vendor and load the three fonts

**Files:**

- Create: `frontend/app/fonts/caprasimo-latin-400.woff2`
- Create: `frontend/app/fonts/figtree-latin-variable.woff2`
- Create: `frontend/app/fonts/geist-mono-latin-variable.woff2`
- Create: `frontend/app/fonts/licenses/Caprasimo-OFL.txt`
- Create: `frontend/app/fonts/licenses/Figtree-OFL.txt`
- Create: `frontend/app/fonts/licenses/Geist-Mono-OFL.txt`
- Create: `frontend/app/fonts/README.md`
- Modify: `frontend/app/layout.tsx`

**Interfaces:**

- Consumes: the existing CSS variables `--font-caprasimo`, `--font-figtree`, and `--font-geist-mono` used by `frontend/app/globals.css`.
- Produces: `caprasimo.variable`, `figtree.variable`, and `geistMono.variable` class names with no build-time or runtime Google Fonts request.

- [x] **Step 1: Reproduce the failing production build**

Run: `cd frontend && npm run build`

Expected: FAIL because `next/font/google` cannot fetch Caprasimo, Figtree, and Geist Mono in the restricted build environment. This is the configuration-only red test; no source-grep unit test is added because it would test implementation text rather than the executable build boundary.

- [x] **Step 2: Download the official Latin WOFF2 assets and OFL licenses**

Run these commands from the repository root; `curl -f` makes HTTP errors fatal:

```bash
mkdir -p frontend/app/fonts/licenses
curl -sS -f -o frontend/app/fonts/caprasimo-latin-400.woff2 "https://fonts.gstatic.com/s/caprasimo/v6/esDT31JQOPuXIUGBp72Ukp8DOJKuGA.woff2"
curl -sS -f -o frontend/app/fonts/figtree-latin-variable.woff2 "https://fonts.gstatic.com/s/figtree/v9/_Xms-HUzqDCFdgfMm4S9DaRvzig.woff2"
curl -sS -f -o frontend/app/fonts/geist-mono-latin-variable.woff2 "https://fonts.gstatic.com/s/geistmono/v6/or3nQ6H-1_WfwkMZI_qYFrcdmhHkjko.woff2"
curl -sS -f -o frontend/app/fonts/licenses/Caprasimo-OFL.txt "https://raw.githubusercontent.com/google/fonts/main/ofl/caprasimo/OFL.txt"
curl -sS -f -o frontend/app/fonts/licenses/Figtree-OFL.txt "https://raw.githubusercontent.com/google/fonts/main/ofl/figtree/OFL.txt"
curl -sS -f -o frontend/app/fonts/licenses/Geist-Mono-OFL.txt "https://raw.githubusercontent.com/google/fonts/main/ofl/geistmono/OFL.txt"
```

- [x] **Step 3: Validate the downloaded binaries before loading them**

Run:

```bash
file frontend/app/fonts/*.woff2
shasum -a 256 frontend/app/fonts/*.woff2
```

Expected: all three files are identified as Web Open Font Format (Version 2); each SHA-256 line contains a non-empty digest and its corresponding filename.

- [x] **Step 4: Record exact asset provenance**

Create `frontend/app/fonts/README.md`:

```markdown
# Vendored fonts

These Latin WOFF2 assets are self-hosted through `next/font/local` so production builds do not depend on Google Fonts network access.

| Local file | Family and range | Official distribution URL | License |
| --- | --- | --- | --- |
| `caprasimo-latin-400.woff2` | Caprasimo 400, Latin | `https://fonts.gstatic.com/s/caprasimo/v6/esDT31JQOPuXIUGBp72Ukp8DOJKuGA.woff2` | `licenses/Caprasimo-OFL.txt` |
| `figtree-latin-variable.woff2` | Figtree 300–900, Latin | `https://fonts.gstatic.com/s/figtree/v9/_Xms-HUzqDCFdgfMm4S9DaRvzig.woff2` | `licenses/Figtree-OFL.txt` |
| `geist-mono-latin-variable.woff2` | Geist Mono 100–900, Latin | `https://fonts.gstatic.com/s/geistmono/v6/or3nQ6H-1_WfwkMZI_qYFrcdmhHkjko.woff2` | `licenses/Geist-Mono-OFL.txt` |

The URLs were resolved from the official Google Fonts CSS2 API using a WOFF2-capable browser user agent on 2026-08-03. To update an asset, resolve the current Latin URL again, download it with HTTP failure handling, verify the `wOF2` magic bytes and SHA-256 digest, then run the production build.
```

- [x] **Step 5: Replace the Google font loader with local font declarations**

In `frontend/app/layout.tsx`, replace the Google-font import and declarations with:

```ts
import localFont from "next/font/local";

const caprasimo = localFont({
  src: "./fonts/caprasimo-latin-400.woff2",
  weight: "400",
  style: "normal",
  variable: "--font-caprasimo",
  display: "swap",
});

const figtree = localFont({
  src: "./fonts/figtree-latin-variable.woff2",
  weight: "300 900",
  style: "normal",
  variable: "--font-figtree",
  display: "swap",
});

const geistMono = localFont({
  src: "./fonts/geist-mono-latin-variable.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-geist-mono",
  display: "swap",
});
```

Retain the existing imports, metadata, theme bootstrap, root element classes, and body structure unchanged.

- [x] **Step 6: Run the focused static checks**

Run:

```bash
cd frontend
npx eslint app/layout.tsx
npm run typecheck
```

Expected: ESLint reports no errors and TypeScript exits successfully.

- [x] **Step 7: Run the complete frontend verification**

Run:

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: the full Vitest suite and Next.js production build pass without fetching Google Fonts.

- [x] **Step 8: Verify the final diff and forbidden import**

Run from the repository root:

```bash
git diff --check
rg -n 'next/font/google' frontend
git status --short frontend/app/layout.tsx frontend/app/fonts
```

Expected: `git diff --check` reports no whitespace errors; `rg` has no matches and exits 1; status lists only the intended font assets, provenance, and layout change within this task's scope.
