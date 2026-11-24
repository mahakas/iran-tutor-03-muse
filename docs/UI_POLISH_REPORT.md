# UI Polish Report (branch `arena/e8b0f850-iran-tutor`)

Status: **partial slice, Verification Gate reached.** The full scope in the
request (admin categorized sidebar, KPI dashboard, all per-screen items,
toasts, lightbox, stepper, timeline, notebook print QA) is NOT complete.

## Status

Slice 1 (merged): font, tokens, header dark toggle, focus/touch/reduced-motion, print rules,
immersive mobile tabs, chat sources cleanup.

Slice 2 (this branch), in order from the request:

| # | Item | Result |
|---|---|---|
| 1 | Admin sidebar with five categories and mobile/tablet drawer | **Done.** `components/AdminSideNav.tsx`. Desktop (≥1024px): sticky sidebar in a two-column `admin-body` grid. Below 1024px: off-canvas drawer with scrim, opened from a full-width toggle. Same tabs and same data-loading side effects as the old flat tab bar. |
| 2 | Toasts | **Done.** `lib/toast.ts` (event bus) and `components/ToastHost.tsx` (mounted once in the root layout; `role=alert` for errors, `status` otherwise). Wired to the provider Test Connection result. |
| 3 | Lightbox for source figures | **Done.** `components/FigureThumb.tsx` loads through the student figure endpoint with the bearer token (object URL), shows a skeleton while loading, a caption, and opens `components/ImageLightbox.tsx` (Escape / close button, focus restored). |
| 4 | Deep Solve stepper | **Done.** Hint 1 → hint 2 → show step → full solution. Stages come from the server's `available_actions`; the stepper only shows position. |
| 5 | Mastery timeline | **Done.** Chapter list is a vertical timeline; node color follows status (mastered / in progress / locked). |
| 6 | Memory Inspector timeline cards | **Done (CSS).** L1/L2/L3 items have a rail and a layer-colored dot (`data-layer`). |
| 7 | Skeletons and Persian empty states | **Partly.** Empty states in Mistake Bank, Notebook list, and flashcard deck. Skeleton used in figure thumbnails only. Other lists not yet wired. |
| 8 | KPI dashboard redesign | **Not done.** |
| 9 | Skill version compare | **Not done.** |
| 10 | Book-processing progress | **Not verified.** Existing progress UI was not changed in this slice. |
| 11 | Chat `dvh` keyboard check on a real phone | **Not verified** (no device). |
| 12 | Visual QA in light/dark, KaTeX/Mermaid/SVG/diff, print preview | **Not verified** (no browser in the sandbox). |

Known issue left as is: `set-state-in-effect` lint errors in existing effects
(`MistakeBankWorkspace` `load()` effect; `ChatRecycleBin` `loadBin` effect). These patterns predate
this slice. `FigureThumb` and `MasteryWorkspace` were written or changed to avoid the pattern.

## Done in slice 1


| Area | Change |
|---|---|
| Font | `@fontsource/vazirmatn` 5.3.0 installed locally; Arabic/Persian subsets 400/500/700 imported in `app/layout.tsx`. Works offline (woff files bundled by `next build`). |
| Tokens | `globals.css` `:root`: paper canvas `#f8f6f1`, Teal `#0f766e`, Teal-dark `#0b5d57`, Deep Indigo `--indigo`, Amber `--amber`, semantic `--success/--warning/--danger`, `--radius-pill`, `--touch-min: 44px`, `--focus-ring`. Default preset in `lib/preferences.ts` updated to match, since runtime inline CSS variables override the stylesheet. |
| Dark mode | Header toggle in `StudentApp.tsx` calls `updatePreferences({appearance:{color_mode}})`. This writes localStorage and syncs the server (existing path). Icon follows `data-theme` through a MutationObserver after mount (no hydration mismatch). |
| Focus & motion | Unified `:focus-visible` ring. `prefers-reduced-motion` media query added on top of the existing user setting. |
| Touch | `pointer: coarse` raises buttons, sidebar items, and admin tabs to 44px. |
| Numbers / code | `tabular-nums` on table cells and KPI grids. `pre`/`code` forced LTR, monospace. Wide content gets `overflow-x: auto`. |
| Responsive | Admin tabs become a horizontal scroll strip below 768px. Student topbar tightened below 640px. Flashcard SM-2 buttons become a 2×2 grid below 640px. |
| Immersive reader | Mobile tab switcher "صفحه کتاب \| گفت‌وگو با معلم" (`role="tablist"`) below 640px; layout stacks to one column. Desktop split view unchanged. |
| Primitives | `.skeleton` (shimmer, reduced-motion safe), `.empty-state` CSS. Not yet wired into screens. |
| Print | `@media print` hides chrome and actions and keeps RTL, for notebook/reading content. Not yet QA'd on a real print preview. |

## Not done in slice 1 (see table above for current status)

- Admin sidebar with categories (dashboard/monitoring, providers/routing, capabilities/Skills, books/KB, users/quotas) and mobile drawer. Currently the three-tab `AdminGate` shell and the internal section state in `app/admin/page.tsx` are unchanged.
- Toast system, lightbox for `source_figures`, Deep Solve stepper, mastery timeline, Memory Inspector timeline cards, provider Test Connection feedback, KPI redesign, Skill version compare, book-processing progress.
- Wiring skeletons and Persian empty states into existing lists.
- Chat `dvh` keyboard-safe input check on real mobile devices.
- Visual QA of KaTeX, Mermaid, SvgDiagram, and diff readability in light and dark themes, and print preview.

## Verification (slice 2)

- `npx tsc --noEmit`: exit 0.
- `npm run build`: exit 0 (after all frontend edits).
- ESLint on all touched files: 2 errors, both pre-existing on `main` (`set-state-in-effect` in `MistakeBankWorkspace` load effect and `ChatRecycleBin` `loadBin` effect), plus one warning for `globals.css` (not linted by config). No new lint errors.
- `pytest -q tests` (backend): 321 passed, 1 skipped. `backend/tests/conftest.py` now forces `ADMIN_USERNAME`/`ADMIN_PASSWORD` for tests, so a developer's `backend/.env` cannot break the admin login tests (previously 23 failed while `.env` was present).
- No `console.log` added. No new `NEXT_PUBLIC_*` variables. No changes to DOMPurify, `securityLevel: "strict"`, `lib/safeVisual.ts`, or SvgDiagram/MermaidDiagram.
- **Not verified:** real browser rendering at 360/768/1024px and in dark mode, and print preview. The sandbox cannot download Playwright's Chromium (CDN blocked), so these checks remain open.
