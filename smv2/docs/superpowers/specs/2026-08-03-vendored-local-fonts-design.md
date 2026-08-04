# Vendored Local Fonts Design

Date: 2026-08-03

## Goal

Make SourceMind's production build independent of Google Fonts network availability while preserving its existing typography: Caprasimo for display headings, Figtree for body text, and Geist Mono for monospace text.

## Decision

Vendor the Latin WOFF2 files for Caprasimo 400, Figtree variable, and Geist Mono variable inside the frontend. Replace `next/font/google` with `next/font/local` in `frontend/app/layout.tsx`, retaining the existing CSS variable names:

- `--font-caprasimo`
- `--font-figtree`
- `--font-geist-mono`

No runtime font request, package dependency, or fallback-font redesign is introduced.

## Asset provenance and security

Download only static WOFF2 font binaries from the official Google Fonts distribution used by the current declarations. Store them under `frontend/app/fonts/` so Next.js fingerprints and serves them as build assets. Record the upstream URL and license alongside the files. Do not execute downloaded content or add font-install scripts.

## Loading behavior

`next/font/local` will register the same CSS custom properties currently consumed by `globals.css`. Figtree and Geist Mono use their variable ranges; Caprasimo remains weight 400. Existing system-font fallbacks remain unchanged if a font cannot load in the browser.

## Failure handling

The download step must fail on HTTP errors and incomplete responses. Each saved file must be non-empty and recognized as WOFF2 before code is changed. If an upstream variable font is unavailable, stop rather than silently substituting a different family or format.

## Verification

1. Verify each vendored asset is a WOFF2 file and record its checksum.
2. Run targeted ESLint and TypeScript checks for the layout.
3. Run the frontend tests.
4. Run the complete production build without requiring outbound font access.
5. Run `git diff --check` and confirm `next/font/google` no longer appears in the frontend.

## Non-goals

- Changing the typography, font weights, or CSS variable names.
- Adding additional language subsets.
- Reworking unrelated build warnings or the existing theme bootstrap script.
