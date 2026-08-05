# Local Workspace Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persisted local workspace mode so learner-facing navigation hides curriculum and validation tooling by default while instructor tooling remains intentionally reachable behind an explicit mode switch.

**Architecture:** Model workspace mode as a local UI preference, not authorization. The header owns the mode switch, the sidebar renders the mode-appropriate navigation, and instructor-only routes show a boundary screen when opened from learner mode instead of silently changing state. This keeps the app local-first, avoids any auth claims, and gives students a clear reason why extra tools exist.

**Tech Stack:** Next.js App Router, React 19, TypeScript 5, Vitest, Testing Library, localStorage-backed hooks.

## Global Constraints

- Keep the feature local-first and single-user.
- Workspace mode is a UI preference only; it is not authorization, access control, or a security boundary.
- The default mode is `learner`.
- The only persisted mode values are `learner` and `instructor`.
- The mode switch should use the same local preference pattern as `useSidebarCollapsed` and `useTheme`.
- Direct navigation to instructor routes while in learner mode must show a boundary screen with an explicit switch action and a back-to-course action.
- No backend API, OpenAPI, or database change is required for this feature.

---

## File Structure

- Create `frontend/lib/hooks/useWorkspaceMode.ts`
- Create `frontend/components/workspace/WorkspaceModeMenu.tsx`
- Create `frontend/components/workspace/WorkspaceModeGate.tsx`
- Modify `frontend/components/SiteHeader.tsx`
- Modify `frontend/components/AppSidebar.tsx`
- Modify `frontend/app/course/[courseId]/curriculum/page.tsx`
- Modify `frontend/app/course/[courseId]/diagnostics/validate/page.tsx`
- Modify `frontend/__tests__/site-header.test.tsx`
- Modify `frontend/__tests__/app-shell.test.tsx`
- Create `frontend/__tests__/workspace-mode.test.tsx`

## Task 1: Add the local workspace-mode hook and disclosure state

**Files:**
- Create: `frontend/lib/hooks/useWorkspaceMode.ts`

**Interfaces:**
- Produces `WORKSPACE_MODE_STORAGE_KEY` with a stable literal key.
- Produces `WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY` for the one-time instructor explanation.
- Produces `WorkspaceMode = "learner" | "instructor"`.
- Produces `UseWorkspaceModeResult { mode, setMode, toggle, disclosureSeen, markDisclosureSeen }` or an equivalent interface with the same responsibilities.
- Consumes `window.localStorage` and `useSyncExternalStore` only; no server-side browser access.

- [ ] **Step 1: Write the failing hook test**

Create a new test file that proves the current code has no workspace-mode persistence or disclosure state:

- `frontend/__tests__/workspace-mode.test.tsx` should render a tiny harness, switch the mode, remount, and verify the selection persists.
- The same test file should verify the instructor disclosure appears once and can be dismissed.

Run:

```bash
cd frontend && npm test -- --run __tests__/workspace-mode.test.tsx
```

Expected: FAIL. The hook file and its persistence contract do not exist yet.

- [ ] **Step 2: Implement the hook and the disclosure state**

Implement the hook with the same module-level pub/sub pattern used by other local preferences in the repo. Keep the disclosure acknowledgement separate from the mode itself so the mode remains a pure preference.

Principal-engineer review gate:

- Reject any implementation that stores workspace mode in React state only, reaches into backend APIs, or treats the disclosure as authorization.

- [ ] **Step 3: Verify the hook contract**

Run:

```bash
cd frontend && npm test -- --run __tests__/workspace-mode.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit the hook**

Commit boundary:

```bash
git add frontend/lib/hooks/useWorkspaceMode.ts frontend/__tests__/workspace-mode.test.tsx
git commit -m "feat(frontend): add local workspace mode preference"
```

## Task 2: Add the header menu and sidebar filtering

**Files:**
- Create: `frontend/components/workspace/WorkspaceModeMenu.tsx`
- Modify: `frontend/components/SiteHeader.tsx`
- Modify: `frontend/components/AppSidebar.tsx`
- Modify: `frontend/__tests__/site-header.test.tsx`
- Modify: `frontend/__tests__/app-shell.test.tsx`

**Interfaces:**
- `WorkspaceModeMenu` owns the visible switch in the header and uses `useWorkspaceMode`.
- `SiteHeader` replaces the decorative avatar with the mode switch, mode label, and the one-time instructor disclosure copy.
- `AppSidebar` hides curriculum and validation links in learner mode and shows them in an explicit instructor-tools section in instructor mode.
- No route, course card, or reader panel should infer mode from URL shape alone.

- [ ] **Step 1: Write the failing header/sidebar tests**

Add tests that assert the current UI does not yet have a mode-aware header or sidebar:

- `frontend/__tests__/site-header.test.tsx` should assert that the right-side avatar slot becomes a workspace-mode control with learner as the default.
- `frontend/__tests__/app-shell.test.tsx` should assert that the sidebar still mounts normally and that the workspace-mode filtering logic has not yet been implemented.

Run:

```bash
cd frontend && npm test -- --run __tests__/site-header.test.tsx __tests__/app-shell.test.tsx
```

Expected: FAIL. The header menu and mode-aware sidebar do not exist yet.

- [ ] **Step 2: Implement the header menu and sidebar filtering**

Add the mode menu component and wire it into the existing header:

- `frontend/components/SiteHeader.tsx` should swap the avatar placeholder for the mode menu.
- `frontend/components/workspace/WorkspaceModeMenu.tsx` should render learner/instructor choices, show the explanation before the first switch into instructor mode, and persist the selected mode locally.
- `frontend/components/AppSidebar.tsx` should hide curriculum and validation links when the mode is learner, then render an explicit `Instructor tools` section when the mode is instructor.

Principal-engineer review gate:

- Reject any implementation that leaves the instructor links visible in learner mode or that makes the header control look like an account menu.

- [ ] **Step 3: Verify the header and sidebar contract**

Run:

```bash
cd frontend && npm test -- --run __tests__/site-header.test.tsx __tests__/app-shell.test.tsx __tests__/workspace-mode.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit the navigation shell update**

Commit boundary:

```bash
git add frontend/components/workspace/WorkspaceModeMenu.tsx frontend/components/SiteHeader.tsx frontend/components/AppSidebar.tsx frontend/__tests__/site-header.test.tsx frontend/__tests__/app-shell.test.tsx
git commit -m "feat(frontend): add learner and instructor navigation modes"
```

## Task 3: Gate instructor routes and preserve the learner default

**Files:**
- Create: `frontend/components/workspace/WorkspaceModeGate.tsx`
- Modify: `frontend/app/course/[courseId]/curriculum/page.tsx`
- Modify: `frontend/app/course/[courseId]/diagnostics/validate/page.tsx`
- Modify: `frontend/__tests__/workspace-mode.test.tsx`

**Interfaces:**
- Produces a shared boundary component that reads the workspace mode and either renders the instructor surface or shows a learner-mode explanation.
- The boundary must expose a `Switch to Instructor mode` action and a `Back to course` action.
- Direct navigation to an instructor route must not silently change the mode.

- [ ] **Step 1: Write the failing route-boundary test**

Extend `frontend/__tests__/workspace-mode.test.tsx` with a route-boundary case:

- When the hook reports `learner`, the curriculum and validation routes should render the boundary text instead of the real page content.
- Switching to instructor mode should keep the user on the requested route and reveal the gated content.

Run:

```bash
cd frontend && npm test -- --run __tests__/workspace-mode.test.tsx
```

Expected: FAIL until the new gate exists.

- [ ] **Step 2: Implement the shared gate and wrap the routes**

Add the reusable gate and apply it to the two instructor-facing pages:

- `frontend/components/workspace/WorkspaceModeGate.tsx` should own the explanatory copy and the two actions.
- `frontend/app/course/[courseId]/curriculum/page.tsx` should render the gate around `CurriculumReview`.
- `frontend/app/course/[courseId]/diagnostics/validate/page.tsx` should render the gate around `DiagnosticValidation`.

Principal-engineer review gate:

- Reject any implementation that redirects the learner route without explanation or that silently flips the mode on direct navigation.

- [ ] **Step 3: Verify the route gate**

Run:

```bash
cd frontend && npm test -- --run __tests__/workspace-mode.test.tsx __tests__/site-header.test.tsx __tests__/app-shell.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit the route boundary**

Commit boundary:

```bash
git add frontend/components/workspace/WorkspaceModeGate.tsx frontend/app/course/[courseId]/curriculum/page.tsx frontend/app/course/[courseId]/diagnostics/validate/page.tsx frontend/__tests__/workspace-mode.test.tsx
git commit -m "feat(frontend): gate instructor routes behind workspace mode"
```

## Task 4: Run the full frontend release gate

**Files:**
- Verify only; no new source files are authorized here.

**Interfaces:**
- Consumes the completed workspace-mode changes.
- Produces evidence that the header, sidebar, and gated routes all respect the learner default and the instructor disclosure.

- [ ] **Step 1: Run the focused frontend regression**

Run:

```bash
cd frontend && npm test -- --run __tests__/workspace-mode.test.tsx __tests__/site-header.test.tsx __tests__/app-shell.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run type and lint checks**

Run:

```bash
(cd frontend && npm run lint)
(cd frontend && npm run typecheck)
```

Expected: both commands pass with no new suppressions.

- [ ] **Step 3: Run the repo build**

Run:

```bash
./build.sh
```

Expected: the full build passes and the workspace-mode changes do not introduce any route or shell regressions.

- [ ] **Step 4: Perform the manual local smoke for the student path**

Run:

```bash
./dev.sh
```

Then open the local app in a browser and verify the learner/instructor path:

- `http://localhost:3000/` loads in learner mode by default and does not show curriculum or validation tools in the ordinary navigation.
- Switch to Instructor mode from the header, then open `http://localhost:3000/course/<course_id>/curriculum` and `http://localhost:3000/course/<course_id>/diagnostics/validate` for a ready local course.
- Switch back to Learner mode and confirm direct navigation to those routes shows the boundary copy with `Switch to Instructor mode` and `Back to course`.

Expected: the browser path matches the explicit mode boundary and does not imply authorization.

Stop the dedicated dev session before any later build or release command; `build.sh` refuses to run while the application ports are occupied.

## Review Gates

- Learner mode must be the default after a fresh load.
- Curriculum and validation controls must disappear from the ordinary student navigation.
- Direct learner-mode navigation into instructor routes must explain the boundary instead of pretending the page is unavailable.
- The mode switch must never claim to be authorization.

## Release Notes

- This plan intentionally keeps workspace mode on the frontend only.
- If a future product decision adds real accounts or permissions, that work should start from a separate security plan, not from this UI preference.
