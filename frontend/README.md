# Frontend

Web client for JDK ERP: **React 19 + TypeScript + Vite + Tailwind v4**
(CSS-first `@theme`, no JS config), matching `jdk_clean`'s stack — that
stack wasn't part of what was messy, so it's reused as-is. Follows
[`docs/ENGINEERING_PRINCIPLES.md`](../docs/ENGINEERING_PRINCIPLES.md) —
in particular Principle 6 (one standard component library) and
Principle 7 (consistent terminology/status colours/confirmation flows
across every module).

## Implemented so far

- **Common UI Components** (`src/components/ui/`, `src/components/forms/`,
  `src/lib/`) — the one shared component library every future module
  screen composes, covering all 8 categories in
  [`../docs/modules/common_ui_components.md`](../docs/modules/common_ui_components.md):
  - **Layout**: `PageHeader`, `Breadcrumbs` (props-driven, no router
    coupling), `Card`, `FormSectionHeading`, `FilterBar`.
  - **Actions**: `Button` (primary/secondary/danger/ghost, `isLoading`,
    forwardRef), `IconButton`, `ActionMenu` (one generic ⋮ menu with
    arrow-key navigation, replacing three near-identical dropdown copies
    in `jdk_clean`).
  - **Forms**: `TextField`, `NumberField` (clamps to min/max on blur),
    `DateField` (date/datetime-local), `SelectField`,
    `MultiSelectField`, `SearchSelectField` (a real ARIA combobox —
    `jdk_clean` had no form-level autocomplete at all), `CheckboxField`,
    `RadioGroupField`, `TextareaField`, `FileUploadField`
    (drag-and-drop + browse, replacing ~9 pages that each hand-rolled
    their own file picker). All ten share one label/error/hint contract
    (`FieldShell`, `useFieldIds`).
  - **Data & Tables**: `DataTable` (sorting, loading/empty/error states,
    pagination, optional column-visibility — generalizes `jdk_clean`'s
    `MasterListPage` shape, which only masters used while ~30 business
    list pages hand-copied the same shell), `SortableHeader`,
    `Pagination`, `Badge`/`StatusBadge` (tone map is caller-supplied and
    domain-scoped, not one global map), `StatCard`, `KeyValue`.
  - **Feedback & States**: `Spinner`, `EmptyState`, `Alert`
    (success/warning/danger/info — `jdk_clean` had no `warning` variant),
    `ConfirmDialog`.
  - **Overlays**: `Modal` (portal + real focus-trap, `initialFocusRef`
    override for destructive dialogs), `Drawer` (shares the same
    focus-trap hook as `Modal`, slides from a side — no equivalent
    existed in `jdk_clean`), `Tooltip` (no equivalent existed).
  - **Navigation**: `TopNav`, `Sidebar` (both driven by the same
    `NavEntry[]` shape and own no auth/business state — `jdk_clean` had
    no sidebar at all, being top-nav-only), `Tabs`/`TabPanel` (full
    WAI-ARIA tablist with roving tabindex and arrow/Home/End navigation).
  - **Standard Data Display**: `Currency`, `NumberDisplay`, `DateTime`,
    `Percentage` (thin wrappers over `src/lib/format.ts` — `jdk_clean`
    had no percentage or plain-number formatter at all), `Avatar`
    (accepts an already-resolved `src`; `jdk_clean`'s version fetched an
    authenticated blob internally regardless of whose avatar was being
    rendered), `UserChip`.

  Design tokens (ink/gold/violet scale, plus new `success`/`warning`/
  `danger`/`info` tokens `jdk_clean` never had) live in `src/index.css`,
  matching [`../docs/DESIGN_SYSTEM.md`](../docs/DESIGN_SYSTEM.md). Icons
  are from `lucide-react` rather than hand-drawn SVG (`jdk_clean` had no
  icon library and a confirmed duplicate icon across two files).
  Deliberately **excludes** a toast/snackbar system (not asked for by
  the spec; `Alert` already covers static/inline success/warning/error
  feedback) and a generic resource-agnostic query-scoping helper for
  tables (no concrete business table exists yet to build one against).
  See [`../docs/audit/COMMON_UI_COMPONENTS_AUDIT.md`](../docs/audit/COMMON_UI_COMPONENTS_AUDIT.md)
  for the full reuse/rebuild verdict per component.

  `src/App.tsx` is a kitchen-sink demo composing every component on one
  page — useful as a quick visual reference and as a live smoke test
  (`npm run dev`) until real module screens replace it.

## Setup

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint
npm run test       # vitest + @testing-library/react
```
