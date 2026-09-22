# Common UI Components — Final Coverage Patch

A coverage-only follow-up to `docs/audit/COMMON_UI_COMPONENTS_AUDIT.md`,
per the 7-point patch request (icon library, charts, context menu,
responsive elements, common utility components, hard rules,
validation). Audited what already exists first; added only what was
genuinely missing. Nothing already built was redesigned, replaced, or
duplicated.

## 1. What was already present

- **Icon library**: `lucide-react` was already the sole icon library
  (added in the original Common UI Components phase), used consistently
  across every existing component — `MoreVertical` (⋮), `ArrowUp/Down/
  UpDown` (sort), `X` (close), `Upload` (file upload), `ChevronDown/
  Left/Right` (navigation), `Columns3` (column visibility), `CheckCircle2/
  AlertTriangle/Info/XCircle` (alert variants). No emoji, no raw
  hand-drawn SVG anywhere except `Spinner` (a genuine exception — an
  animated loading indicator, which lucide has no primitive for). No
  action needed.
- **Visible action menu (⋮)**: `ActionMenu` already existed and already
  satisfied "provide a standard visible action menu."
- **Common utility/display components already covered**: Tooltip,
  Avatar/UserChip, DateTime, Currency/NumberDisplay/Percentage,
  EmptyState. No duplicates created for any of these.
- **Some responsive behaviour already correct**: `FilterBar` already
  collapses multi-column to single-column (`grid-cols-1 sm:grid-cols-2
  lg:grid-cols-4`); `DataTable`'s table already scrolls horizontally
  (`overflow-x-auto`) rather than shrinking columns; `Modal`/`Drawer`
  were already full-width-with-padding on narrow screens.

## 2. Genuine gaps identified

- **Charts/graphs**: no charting library, no chart component, of any
  kind existed.
- **Right-click context menu**: no context-menu capability existed at
  all (only the visible ⋮ menu).
- **Responsive gaps** (found by an actual audit of the rendered
  components, not assumed):
  - `DataTable` had no way to drop a secondary column on narrow
    screens — it either showed every column (causing horizontal scroll)
    or hid one entirely via the manual column-visibility toggle. No
    breakpoint-driven "hide below" behaviour existed.
  - `Sidebar` had no mobile/off-canvas behaviour at all — it was a
    persistent flex child that would either force horizontal overflow
    or crowd out content on a narrow screen.
  - `Tabs`' tablist had no overflow handling, so a page with several
    tabs could overflow its container width.
  - No responsive grid existed for a row of `StatCard`s — the original
    demo had hand-rolled a fixed 3-column grid that never collapsed.
  - **Found only by live-viewport testing, not by reading the
    code**: `TopNav` itself overflowed horizontally on a 390px-wide
    viewport (its inline nav-entries list plus slotted actions don't
    fit). This wasn't visible from a code read since nothing in `TopNav`
    looked obviously wrong — it only showed up under an actual narrow
    viewport with real content, which is exactly why the validation
    step of this patch mattered.
- **Common utility/display components genuinely missing**:
  copy-to-clipboard, a progress indicator, a skeleton/loading
  placeholder, an access-denied state, a page-level error state, and an
  unsaved-changes warning. None of these existed under any name.

## 3. What was added/changed

**Charts** (`frontend/src/components/charts/`) — one JDK-owned
abstraction over `recharts`: `ChartState` (shared loading/empty/error
handling, composing the existing `Spinner`/`EmptyState`/`Alert` rather
than reimplementing them, plus `ResponsiveContainer` for sizing),
`LineChart`, `BarChart` (a `stacked` boolean covers "stacked bar" as a
variant, not a second component), `PieChart` (a `donut` boolean covers
"pie/donut" as a variant), and `palette.ts` (a default series palette
that reads the same `--color-*` CSS custom properties as the rest of the
UI, not a separate colour list). KPI/stat card is **not** duplicated —
the existing `StatCard` already covers it. Every chart takes a
`valueFormatter`, so modules pass `formatCurrency`/`formatPercent`/etc.
from the existing `lib/format.ts` rather than the chart inventing its
own formatting. Modules never import `recharts` directly.

**Context menu** (`frontend/src/components/ui/ContextMenu.tsx`) — a
right-click menu for dense desktop workflows, **always paired with**
the existing `ActionMenu` on the same row/card, offering the identical
`options` array, never a replacement for it. To avoid duplicating the
option-list rendering and arrow-key navigation, that logic was pulled
out of `ActionMenu` into a shared internal `MenuPanel`
(`frontend/src/components/ui/MenuPanel.tsx`) — `ActionMenu`'s public API
and rendered DOM are unchanged, confirmed by its original, unmodified
test suite still passing.

**Responsive fixes**:
- `DataTable`: a new optional `hideBelow: 'sm' | 'md' | 'lg'` per
  column, applied as a literal Tailwind responsive class
  (`hidden md:table-cell`, etc.) on both header and cell — a column
  drops below that breakpoint instead of forcing a scroll, while
  `alwaysVisible` columns (name, status, row actions) stay put.
- `Sidebar`: new optional `mobileOpen`/`onMobileClose` props. Below
  `md`, the sidebar is off-canvas by default and slides in as an
  overlay with a backdrop (closes on backdrop click or Escape) when the
  app sets `mobileOpen`; at `md` and above both props are ignored and
  the sidebar behaves exactly as before. Omitting the new props leaves
  existing usage byte-for-byte unaffected.
- `Tabs`: added `overflow-x-auto` to the tablist container so a page
  with many tabs scrolls horizontally within the tab bar instead of
  overflowing the page.
- `TopNav`: the inline nav-entries `<nav>` is now `hidden md:block` —
  below `md` the app is expected to expose navigation via `Sidebar`
  (opened through a hamburger button placed in `TopNav`'s `logo` slot,
  as the kitchen-sink demo now does), rather than cramming the same nav
  twice into a header that has no room for it.
- New `StatGrid` component: the same collapse-to-fewer-columns pattern
  as `FilterBar`, for a responsive row of `StatCard`s.

**Common utility/display components** (all in
`frontend/src/components/ui/` unless noted):
- `CopyToClipboard` — an icon button (`Copy`/`Check` icons) using
  `navigator.clipboard`, with a brief "Copied" state via the existing
  `Tooltip`; fails silently if clipboard access is denied (a
  convenience action, not a critical one).
- `ProgressBar` — a determinate 0–100% bar (`role="progressbar"`,
  proper `aria-valuenow/min/max`).
- `Skeleton` — a loading placeholder block, sized via `className`;
  distinct from `Spinner` (indeterminate whole-section wait) — this is
  for a layout that's about to be filled in.
- `AccessDeniedState` — mirrors the backend's `ACCESS_DENIED` error
  contract (`backend/app/core/errors.py`) with matching intent, distinct
  from `EmptyState` ("nothing here yet" vs. "you can't see this").
- `PageErrorState` — a full-section counterpart to the inline `Alert`,
  with an optional retry action; its default message matches the
  backend's generic `SERVER_ERROR` fallback text, so the same failure
  reads identically on both ends of the stack.
- `useUnsavedChangesGuard` (`frontend/src/lib/`) — a hook that warns on
  tab close/refresh while a form is dirty, via the native `beforeunload`
  prompt. Deliberately does **not** block in-app route navigation:
  react-router's `useBlocker` needs a data router
  (`createBrowserRouter`), and this app currently uses declarative
  `<BrowserRouter>` with no routes or forms built yet — adopting a data
  router now, before anything needs it, would be exactly the kind of
  architecture change the patch's own hard rules forbid ("no new
  framework or architectural layer unless genuinely required"). Until a
  data router exists, a form's own Cancel/Back handler can check the
  same `isDirty` flag and confirm via the existing `ConfirmDialog` —
  documented as the interim pattern rather than left silently unhandled.

**Bundle size**: `recharts` (plus its `d3-*` internals) is by far the
largest dependency added. `vite.config.ts` now splits it into its own
`vendor-charts` chunk via `manualChunks`, so the main app bundle is
unchanged in size (still ~302 KB / ~93 KB gzip) and pages that render no
charts never load it. This kitchen-sink demo page happens to render
every component including charts on one route, so its own initial load
does pull the chart chunk — that's an artifact of there being only one
demo page today, not a real routing structure; once Phase 2 introduces
actual routes, route-level code-splitting (`React.lazy`) will mean only
screens that use charts load that chunk at all.

## 4. Dependencies added

- **`recharts` `^3.10.1`** — the same version `jdk_clean` already used
  (React 19-compatible), reused rather than picking a different library.
  This is the only new dependency; every other addition (context menu,
  responsive fixes, utility components) uses only what was already
  installed (React, Tailwind, `lucide-react`, the native Clipboard API).

## 5. Tests/checks performed

- 45 new tests added (Charts: 10 across Line/Bar/Pie covering
  loading/error/empty/rendered-with-data; ContextMenu: 5; DataTable
  `hideBelow`: 1; Sidebar mobile overlay: 3; StatGrid: 1; the 6 new
  utility components + `useUnsavedChangesGuard`: 25) — full suite now
  **156 passing** (up from 155... 111 before this patch), zero
  failures.
- **Zero regressions**: every pre-existing test, including `ActionMenu`'s
  full original suite (unmodified), passes unchanged after extracting
  `MenuPanel` — confirming the refactor didn't alter `ActionMenu`'s
  behaviour.
- `jsdom` needed two standard shims to test `recharts` at all (a
  `ResizeObserver` polyfill that actually invokes its callback with a
  synthetic entry, and fixed `offsetWidth`/`offsetHeight`/
  `getBoundingClientRect` values) — added to `src/test/setup.ts`,
  scoped to what `ResponsiveContainer` needs and not used by anything
  else.
- Lint clean (`eslint .`), build clean (`tsc -b && vite build`) — the
  build step caught a real type error the test suite and linter both
  missed (a `recharts` `Tooltip` formatter signature mismatch), fixed by
  coercing the value inside the formatter instead of narrowing its
  parameter type.
- **Live-verified** with a real `vite` dev server + Playwright/Chromium,
  at both a desktop viewport (1400×1000) and a phone viewport
  (390×844):
  - Desktop: Modal, Drawer, the visible ActionMenu, the TopNav group
    dropdown, Tabs switching, Sidebar collapse, Tooltip, the new
    ContextMenu (right-click opens the same options as the paired
    ActionMenu, Escape and outside-click close it), CopyToClipboard (a
    real clipboard write plus the "Copied" state), and all three chart
    types (including their loading/empty/error states) — all
    screenshotted, zero console/page errors throughout.
  - Mobile: confirmed `document.documentElement.scrollWidth ===
    clientWidth` (**no horizontal page overflow**) only after finding
    and fixing the `TopNav` overflow described above — the first pass
    genuinely failed this check, which is exactly what this validation
    step is for. Also confirmed: the hamburger button opens `Sidebar` as
    a backdrop-dimmed overlay that closes on Escape/backdrop click;
    `DataTable`'s `hideBelow="md"` column (Balance) is correctly hidden
    while `alwaysVisible` columns (Name, Status) stay visible and
    usable; forms/`FilterBar` stack to a single column with actions
    still reachable; `Tabs` and `StatGrid` reflow correctly at that
    width.
  - One real rendering bug was found and fixed during this pass: the
    Y-axis of `LineChart`/`BarChart` clipped currency-formatted tick
    labels (e.g. `"$45,000.00"`) against the chart's left edge, because
    the axis was given no reserved width. Fixed with an explicit
    `width={80}` on both charts' `YAxis` plus a small left margin.
    (A separately-suspected "broken pie chart" — sectors clustered into
    a small arc instead of a full circle — turned out to be `recharts`'
    default entrance animation caught mid-frame by an immediate
    screenshot, not a bug; confirmed by re-screenshotting after the
    animation settles.)

## 6. Remaining genuine gaps

- **In-app unsaved-changes blocking** (as opposed to the tab-close/
  refresh warning, which is built) needs a data router
  (`createBrowserRouter` + `useBlocker`), which this app doesn't use yet
  and has no current reason to adopt. Documented as a decision, not an
  oversight — revisit when the app's first real route/form exists.
- **Column-visibility state and any future "remember my chart type/
  table density" preference are not persisted** (no `localStorage`
  wiring) — not asked for by this patch and would be speculative without
  a concrete screen asking for it.
- **A custom checkbox-list combobox for `MultiSelectField`** remains a
  possible future upgrade over the current native `<select multiple>`
  (noted in the original audit, unchanged by this patch) if its native
  appearance becomes a real complaint once Phase 2 screens are built —
  not a gap this patch's scope covers.
