# Common UI Components — Audit

Audit of `jdk_clean/frontend` (React 19 + TypeScript + Vite + Tailwind v4)
against the 8 categories in `docs/modules/common_ui_components.md`, to
decide what's reused in shape vs. rebuilt fresh in `jdk_erp`. Full
evidence (file:line citations) gathered by a background research agent
reading every file under `frontend/src/components/{ui,layout,master,
status,history}/`, the `lib/` formatters, `index.css`, and `package.json`,
plus targeted greps for gaps (tooltip, multi-select, autocomplete, file
upload, column visibility, toast). Summary below; verdicts are per
category, with the concrete evidence that drove each one.

## Stack decision

Reuse jdk_clean's stack as-is — it isn't part of what was messy:
**React 19 + TypeScript + Vite + Tailwind v4 (CSS-first `@theme`, no JS
config) + react-hook-form + zod + react-router-dom + vitest/testing-library**
(the last two are new — jdk_clean's frontend has zero tests of any kind,
a real gap this rebuild does not repeat, matching the backend's 100%-test
discipline). One addition: **lucide-react** for icons (see "Icon system"
below) — jdk_clean has no icon library at all.

## 1. Layout

**Reuse in shape**: `PageHeader` (title/subtitle/actions triad), `Tabs`
(see §6 — the single best-built component found, full WAI-ARIA tablist),
`GlassCard`→renamed `Card` (thin `HTMLAttributes<HTMLDivElement>`
wrapper, no business logic), `FormSectionHeading`'s `first:` border trick
for section lists.

**Concrete defect to not repeat**: `PageHeader` exists but is *underused*
— `MasterListPage.tsx:84-92` and `OrdersListPage.tsx:54-58` both
hand-roll the identical header markup instead of importing it. Every
future jdk_erp list/detail page must compose `PageHeader`, never
re-declare its JSX.

**Gap — no spacing/grid primitive**: jdk_clean has no shared `Grid`/
`FilterBar`; `MasterListPage.tsx:96-99` inlines a one-off
`style={{gridTemplateColumns}}`. Fresh design: a small `FilterBar`
component (a labeled-row-of-controls grid) rather than each page inlining
its own filter layout.

**Breadcrumbs — reuse the a11y shape, not the coupling**: jdk_clean's
`Breadcrumbs.tsx` is correct (`nav aria-label`, `aria-current="page"`)
but pulls its trail from `useLocation()` + a hand-maintained path→label
registry, hard-wiring app routing into the component. jdk_erp's version
takes `items: {label, to?}[]` as a prop; the app computes the trail.

## 2. Actions

**Reuse in shape — `Button`**: variant/size enums, `isLoading` built in
(`aria-busy`, spinner overlay without width jump), forwardRef, spreads
native props. Directly portable API.

**Gap — no `IconButton`**: three separate call sites
(`ApprovalMenu.tsx:80`, `DownloadMenu.tsx:88`,
`StatusTransitionButtons.tsx:93`) hand-roll the same `!w-9 !px-0`
override on `Button` instead of a real icon-only variant. Fresh: a small
`IconButton` wrapping `Button` with a required `aria-label` (no visible
text) and fixed square dimensions.

**Rebuild fresh — action menu (⋮)**: `DownloadMenu.tsx` and
`ApprovalMenu.tsx` are near-identical, copy-pasted dropdown
implementations (byte-for-byte identical outside-click/`Escape` handling
at `DownloadMenu.tsx:51-67` vs `ApprovalMenu.tsx:43-59`) — and
`NavDropdown.tsx:41-59` is a *third* independent copy of the same
pattern. None of the three do arrow-key navigation between items, unlike
`Tabs`'s much more complete keyboard handling. jdk_erp builds **one**
generic `ActionMenu` (trigger + `options: {key,label,onSelect,disabled}[]`)
backed by a shared `useDismissableOverlay` hook, with the a11y rigor
raised to `Tabs`'s level (arrow-key nav, focus moved into the panel on
open).

## 3. Forms

**Reuse in shape — the label/error/hint contract**: `TextField`,
`SelectField`, `RadioGroupField`, `TextareaField` all share one
convention — required `label`, optional `error` (shown via `role="alert"`
+ `aria-invalid`/`aria-describedby`), optional `hint` (same
`aria-describedby` slot), `useId()`-generated ids when none is given.
This is the best reusable shape in the whole audit — it's the base
contract for every jdk_erp form field, not just the ones jdk_clean
already has.

**Gaps — no precedent exists at all for**: a dedicated **number input**
(jdk_clean uses bare `<TextField type="number">` per call site, with
clamping logic — `lib/number.ts`'s `clampNonNegative` — applied by hand
each time instead of built into the field); **date/date-time input**
(zero dedicated component; `CalendarModal.tsx` is a full scheduling
widget wired to its own API, not a form field); **checkbox** (no file
exists anywhere); **multi-select** (zero hits for `MultiSelect`/
`multiple` as a component); **search/autocomplete** (zero hits for
`Autocomplete`/`Combobox`; the closest analogs — the global command
palette and the assistant drawer's search — are full-app search UIs, not
a form-field-level "pick one record" control); **file upload** (~9 pages
each hand-roll their own file-picker/preview instead of one shared
component — `AvatarEditor.tsx`, `CustomerAvatarPanel.tsx`,
`IdDocumentPanel.tsx`, `IdDocumentPicker.tsx`, and 5 more).

All six get fresh designs, built on the same label/error/hint contract as
the reused fields.

## 4. Data & Tables

**Reuse in shape**: `SortableHeader` (though its sort-state convention —
a bare string with a `-` prefix for descending — is replaced with an
explicit `{ field, direction: 'asc'|'desc'|null }` shape, still simple,
no string-parsing at each consumer); `Pagination` (`null`-returns when
`totalPages<=1`, so callers never need a conditional); `Badge`/
`StatusBadge`'s two-tier shape (generic tone-based badge + status-aware
convenience wrapper); `Field` (key-value/detail view — dt/dd pair,
`'—'` empty fallback).

**Rebuild fresh — the table shell itself**: `MasterListPage.tsx` has a
genuinely good generic shape (`MasterListColumn<T> { key, label,
sortable?, render, align? }`, a render-prop escape hatch for rare filter
needs) — but it's used only by the small "master data" list pages. Every
real business list page (Orders, Customers, Products, Quotations,
PurchaseOrders, ProductionOrders, DeliveryNotes, and ~20 more — 30+ files
found via grep) hand-copies the identical
`Card > table > SortableHeader/th > Pagination` shell instead
(`OrdersListPage.tsx:109-156` duplicates `MasterListPage.tsx:122-166`
almost verbatim). This is the largest duplication finding in jdk_clean.
jdk_erp generalizes `MasterListPage`'s column-as-data shape into **one**
`DataTable` component every list page composes — masters and business
lists alike — with a fully injectable filter bar (not a hardcoded
"Active/Inactive" pair, unlike `MasterListPage.tsx:111-114`) so no future
module has a reason to hand-roll the shell again.

**Gaps — no precedent**: column visibility (zero hits anywhere for
`columnVisibility`/`hideColumn`) and a summary/stat card (no
`StatCard`/`SummaryCard` exists; dashboards build stat tiles ad hoc on
`GlassCard`). Both get fresh designs — column visibility as a popover of
checkboxes on `DataTable`, `StatCard` built on `Card`.

**Status vocabulary — decouple from a single flat map**: jdk_clean's
`STATUS_TONES` (`Badge.tsx:22-59`) is one 30+-entry map shared across
every domain (order/QC/PO statuses all in one namespace) — it only
avoids collisions today because the strings happen not to overlap.
jdk_erp's `StatusBadge` takes the tone (or a status→tone map) as a prop
from the caller instead of a single hardcoded global map, since Phase 2
hasn't defined any business status vocabulary yet and baking one in now
would be designing for a module that doesn't exist (Engineering
Principle: no caller, no abstraction).

## 5. Feedback & States

**Reuse in shape**: `Spinner` (inline SVG, no external dependency,
`role="status"`), `EmptyState` (title/message/action), `Alert`'s
render-nothing-when-falsy convention (`<Alert variant="error">{error}</Alert>`
unconditionally, no `{error && ...}` at every call site — a genuinely
good ergonomic API worth calling out explicitly), `ConfirmDialog`
(a clean example of composing `Modal` rather than duplicating it).

**Fix on the way in**: jdk_clean's `Alert` only has `error`/`success`/
`info` variants — no `warning`, despite the spec listing "warning/alert"
explicitly. jdk_erp's `Alert` ships all four (`success`/`warning`/
`danger`/`info`) from the start, mapped onto the new theme tokens (see
"Design tokens" below) rather than raw Tailwind colors.

**Deliberately excluded**: a toast/snackbar system. jdk_clean has none
(no such dependency in `package.json`), and the spec's own checklist
lists "Success message" as a Feedback & States item alongside
"Warning/alert" — both read as inline/static feedback, which `Alert`
already covers. Building a transient-notification system isn't
something the spec asks for; adding one now would be exactly the kind of
building-beyond-the-requirement the module's own "Core rule" forbids.

## 6. Overlays

**Reuse almost verbatim — `Modal`**: this is the best-documented, most
accessible component in the entire jdk_clean codebase. Rendered via
`createPortal` to `document.body` (with a documented reason: escaping
`AppLayout`'s sticky-header stacking context), a real focus-trap
(captures and restores the previously-focused element, auto-focuses the
first focusable element on mount, traps Tab/Shift+Tab), `Escape`-to-close,
correct ARIA (`role="dialog"`, `aria-modal`, `aria-label`), and three
well-reasoned size variants. jdk_erp's `Modal` is built directly from
this design — the focus-trap and portal-stacking-context reasoning
carries over as-is. One addition: an `initialFocus` override, since
`Modal.tsx` always focuses the first focusable element, which is the
wrong default for a destructive confirm dialog (should default focus to
Cancel, not the danger button).

**Gap — no generic Drawer**: the only slide-in panel that exists
(`AssistantDrawer.tsx`) is a fully business-specific AI-chat-and-search
widget with no reusable `open/title/children` API — nothing there is
extractable. jdk_erp's `Drawer` is a fresh component built on the *same*
focus-trap/portal groundwork as `Modal` (shared via one `useFocusTrap`
hook so the logic isn't duplicated a second time), just animating in
from a side instead of scaling from center.

**Gap — no Tooltip anywhere**: only the native, unstyled `title`
attribute is used (`StatusTransitionButtons.tsx:96,111`) — no delay
control, no positioning, no theme consistency. Fresh design, no
precedent to reuse.

**Action menu**: covered in §2 — same `ActionMenu` primitive serves this
category's "visible context/action menu" too.

## 7. Navigation

**Reuse in shape**: `Tabs`, `Breadcrumbs` (as a props-driven component,
per §1).

**Rebuild fresh — top nav**: `AppLayout.tsx` (~440 lines) is the top
navigation, but it's inseparably fused to business/app state — auth,
per-role page-permission filtering, notification polling, a hardcoded
nav tree, and three page-specific overlays (command palette, calendar,
assistant drawer) all imported directly. Nothing here can be lifted into
a standalone design-system component as-is. The shape worth keeping is
the split between "chrome" (sticky header, logo, icon-button cluster,
user display) and "nav data" (a declarative `NavEntry[]` union of leaf
and group entries) — jdk_erp's `TopNav` accepts nav entries and slotted
actions as props and owns no business state itself; the app wires its
own nav tree and auth/permission filtering in from outside.

**Gap — no sidebar at all**: jdk_clean is 100% top-nav; there is no
collapsible/persistent side navigation anywhere to audit, and
`NavDropdown`'s flyout is a top-nav dropdown, not a sidebar (it doesn't
address persistent width, collapse/expand, or icon-only collapsed state).
Since the spec explicitly lists "Sidebar" as a Navigation component,
jdk_erp builds one fresh: a `Sidebar` component taking the same
`NavEntry[]` shape as `TopNav`, collapsible, with no embedded business
logic — either can be composed into an app shell depending on which
navigation style a given screen calls for.

## 8. Standard Data Display

**Reuse the convention, not the exact code**: `lib/currency.ts`
(`formatCurrency`) and `lib/dateFormat.ts` (`formatDate`/`formatDateTime`)
are both well-documented, single-purpose, explicit-null-handling
utilities — reuse that *shape* (one function per concern, explicit `'—'`
for missing values, no bare `toLocaleString()`/browser-locale
dependence). Two changes: `formatCurrency` is parameterized by currency
code instead of hardcoded to `KWD`, since jdk_erp has no currency
decision baked in yet (`Organisation.currency` already exists as a
per-organisation field in the backend); `formatDate`/`formatDateTime`
keep the same "one fixed, explicit format app-wide" principle.

**Gaps — no centralized precedent**: a plain **number formatter**
(`lib/number.ts` is an input-clamp utility, not a display formatter — no
thousand-separator helper exists) and a **percentage formatter** (every
percentage in jdk_clean is raw string interpolation,
`` `${value}%` ``, with no shared `formatPercent()` and no consistent
decimal-place rule anywhere). Both built fresh, following the same
"'—' for missing, one function, no ad hoc interpolation" convention.

**Status/state**: covered by `StatusBadge` (§4).

**User/person display — fix a real coupling issue, not just a style
gap**: `Avatar.tsx` fetches an authenticated blob via
`fetchAvatarBlob()` internally on every render, regardless of whose
`avatarUrl` was passed in — worth treating as a correctness risk in
jdk_clean (every `<Avatar>` on screen may resolve to the *current
logged-in user's* photo rather than the person actually being displayed),
not just a portability concern. jdk_erp's `Avatar` accepts a plain,
already-resolved `src: string | null` — fetching is the caller's
responsibility, which also makes the component trivially testable and
portable. No `UserChip` (avatar + name + role in one piece) exists in
jdk_clean either — every call site hand-composes it; jdk_erp adds one.

## Design tokens & infrastructure

**Success/warning/danger/info tokens — a real gap to close, not carry
forward**: jdk_clean's `index.css` has the ink/gold/violet scale
matching `docs/DESIGN_SYSTEM.md` exactly, but **no** `--color-success-*`/
`--color-warning-*`/`--color-danger-*`/`--color-info-*` tokens exist at
all — every component picks a raw Tailwind color ad hoc (`Badge.tsx` uses
`emerald`/`red`/`violet`; `Alert.tsx` uses `emerald`/`red`/`sky` — note
`Alert` and `Badge` use two *different* colors, `sky` vs. `violet`, for
the same "info" meaning, a confirmed real inconsistency). jdk_erp's
`index.css` defines all four tokens from day one (already scaffolded —
see `frontend/src/index.css`) and every status-bearing component
(`Alert`, `StatusBadge`, field error states) reads from them, closing off
the possibility of this exact drift happening again.

**Fonts**: Playfair Display (display) + Inter (body), self-hosted via
`@fontsource/*` — reused exactly as jdk_clean has it; already scaffolded.

**Icon system — adopt a library instead of continuing hand-drawn SVG**:
jdk_clean has no icon library dependency; icons are 100% hand-written
inline SVG, split inconsistently between a proper `icons/` folder (15
components) and one-off inline `<svg>` markup in page/layout files, with
at least one exact duplicate (the dropdown chevron, implemented
separately in `NavDropdown.tsx:96-110` and `DownloadMenu.tsx:100-109`).
jdk_erp adopts **lucide-react** — thin stroke, `currentColor`, rounded
caps, a natural match for the existing line-icon aesthetic — eliminating
this maintenance burden rather than promoting ~20 one-off SVGs into a
folder by hand.

## Summary

| Category | Verdict |
| --- | --- |
| 1. Layout | Reuse-in-shape (PageHeader, Tabs, Card, FormSectionHeading) / gap (Grid/FilterBar) |
| 2. Actions | Reuse-in-shape (Button) / gap (IconButton) / rebuild-fresh (ActionMenu, unifying 3 duplicated menus) |
| 3. Forms | Reuse-in-shape (label/error/hint contract) / gap (Number, Date, Checkbox, MultiSelect, Autocomplete, FileUpload) |
| 4. Data & Tables | Reuse-in-shape (SortableHeader, Pagination, Badge/StatusBadge, Field) / rebuild-fresh (DataTable, unifying 30+ duplicated table shells) / gap (column visibility, StatCard) |
| 5. Feedback & States | Reuse-in-shape (Spinner, EmptyState, Alert's falsy-render convention, ConfirmDialog) / fix (add `warning` variant) |
| 6. Overlays | Reuse-almost-verbatim (Modal) / gap (Drawer, Tooltip) |
| 7. Navigation | Reuse-in-shape (Tabs, Breadcrumbs) / rebuild-fresh (TopNav, decoupled from business state) / gap (Sidebar) |
| 8. Standard Data Display | Reuse-the-convention (Currency, Date/DateTime) / gap (Number, Percentage, UserChip) / fix (Avatar's internal-fetch coupling) |

Every gap above is designed fresh in the implementation, following the
conventions the reused components already established (label/error/hint,
`'—'` for missing values, forwardRef + native prop spreading, portal +
focus-trap for overlays) rather than inventing new ones per component.
