# Tables / Forms / Modals / Filters — Audit

Audit of the existing Common UI Components layer
(`docs/modules/common_ui_components.md` + its coverage patch) against
`docs/modules/tables_forms_modals_filters.md`. This is a harden-and-extend
pass, not a rebuild — `DataTable`, the ten form fields, `Modal`/`Drawer`/
`ConfirmDialog`, and `FilterBar` already exist and are reused as-is
wherever they already satisfy a requirement.

## Common Tables

**Already covered, no change**: column definitions, sorting
(`sort`/`onSortChange`, controlled by the caller — `DataTable` never
sorts `rows` itself, so a caller wired to a real API is already
"server-side sort" by construction, not client-side), pagination
(`page`/`totalPages`/`total`/`onPageChange`, same controlled shape),
loading/empty/error states, responsive behaviour (`hideBelow`,
horizontal scroll), status badges (`StatusBadge`), column visibility
(`enableColumnVisibility`), row action menu (a column's `render` can
already put an `ActionMenu` in a row — no dedicated "actions column"
concept needed beyond that). Search/filtering are deliberately not
`DataTable`'s job (composed via `FilterBar` above it) — confirmed
correct by the spec's own "the relationship" section: Table displays,
Filter narrows.

**Genuine gaps**:
- **Row selection** — no checkbox column, no selection state at all.
- **Bulk actions** — depends on row selection; nothing exists.
- **Sticky header** — listed as "optional where genuinely needed"; cheap
  and safe to add as an opt-in prop.
- **A concrete "don't fetch all records to filter/sort in the browser"
  pattern** — `DataTable` being controlled already avoids the anti-pattern
  structurally, but there's no reusable hook for the actual server round
  trip (page/sort/filter → request → loading/error/rows), so every future
  module would hand-roll that data-fetching glue itself. One shared hook
  closes this instead of leaving it to be reinvented per module.

## Common Forms

**Already covered, no change**: text, number, date/date-time, select,
multi-select, search/autocomplete, checkbox, radio, textarea, file
upload (all ten from the original module); labels, help text,
field-level validation/error messages (the shared `FieldShell`
contract); Save/Cancel as a concept (`Button`/`ConfirmDialog` already
exist); the tab-close/refresh unsaved-changes warning
(`useUnsavedChangesGuard`, built in the coverage patch).

**Genuine gaps**:
- **Currency field type** — the spec lists it separately from "Number,"
  and no field renders a currency-formatted value with correct
  decimals/symbol; today a module would reuse `NumberField` and lose the
  formatting. `formatCurrency` already exists in `lib/format.ts`
  (built for the *display*-only `Currency` component) but nothing wires
  it into an editable field.
- **Required indicators** — no field visually marks itself as required,
  even though every field already forwards the native `required`
  attribute through to its underlying `<input>`/`<select>`/`<textarea>`.
- **Read-only visual state** — `disabled` has a style
  (`disabled:opacity-50`); a `readOnly` field (still submits its value,
  unlike `disabled`) has no distinguishing style at all today.
- **Form-level loading/submitting + Save/Cancel as one reusable
  piece** — `Button.isLoading` exists, but every form would
  hand-assemble its own Cancel/Save row and remember to disable Cancel
  while submitting; no shared piece does this once.
- **The "one form system" claim is unverified** — `react-hook-form`,
  `@hookform/resolvers`, and `zod` have been dependencies since the
  project's first commit, and every field's props are plain native
  input attributes (compatible with RHF's `register()` by construction),
  but nothing in the codebase actually demonstrates the three wired
  together end to end. This audit does not consider that a documented
  capability until a test proves it.

## Common Modals / Dialogs

**Already covered, no change**: confirmation dialog (`ConfirmDialog`,
already handles cancel/delete/approve/reject/deactivate — it's generic
over title/message/confirmLabel/danger); detail dialog/drawer
(`Drawer` already is exactly this — "quickly viewing record information
without leaving the current page" is `Drawer`'s stated purpose).
Consistent title/actions/spacing/close behaviour is already true because
everything shares `Modal`'s single implementation.

**Genuine gaps**:
- **Form dialog** — the spec names this as one of the four fixed
  dialog patterns. `Modal` supports arbitrary children plus a footer
  today, so a form *can* go in one, but every call site would
  re-assemble the same Cancel/Save-with-loading footer by hand. A thin
  named wrapper closes this the same way `ConfirmDialog` already closes
  the confirmation pattern.
- **Alert/message dialog** — `ConfirmDialog` always renders two buttons
  (Cancel + Confirm), which is the wrong shape for "important
  information, warnings and errors" that just need an acknowledgement,
  not a decision. No single-button dialog exists.

**Rules requiring no code**: "no nested modals" and "don't put large
workflows inside modals" are call-site discipline, not something to
runtime-enforce speculatively with no current violator — documented in
this file and the module doc instead of adding detection code nothing
would trigger yet.

## Common Filters

**Already covered, no change**: `FilterBar` (the responsive grid every
filter row sits in), and the individual controls a filter row
composes — `TextField` (search), `SelectField` (status/type/category),
`SearchSelectField` (user/owner/customer/supplier — "pick one record via
search," exactly this spec's own examples), `DateField` (a single date).

**Genuine gaps**:
- **Date range** — the spec explicitly lists "date/date range" as one
  filter type; only a single-date field exists today.
- **Clear indication of active filters** — nothing shows which filters
  are currently applied as a scannable summary, or lets one be removed
  individually.
- **Apply / Clear as a standard behaviour** — today a module would need
  to invent its own state shape and its own Apply/Clear wiring per
  screen; no shared hook exists, which directly risks "different filter
  systems per module" for the exact same reason the forms gap does.
- **"More filters" for advanced/less-used fields** — no collapsible
  disclosure pattern exists to keep the common filters immediately
  visible while advanced ones stay out of the way until asked for.
- **Preserve filter state where useful** — without a shared hook owning
  filter state, "preserve state" (e.g. across a tab switch) has no
  common answer today.

## What's added

| Area | Added |
| --- | --- |
| Tables | Row selection (`DataTable` `selectable`/`selectedKeys`/`onSelectionChange`), `stickyHeader` prop, `BulkActionsBar`, `useServerTable` hook |
| Forms | `CurrencyField`, a `required` indicator threaded through `FieldShell` and every field, a `readOnly` style in `inputClasses`, `FormActions`, an integration test proving react-hook-form + zod + these fields work together |
| Modals | `FormDialog`, `AlertDialog` |
| Filters | `useFilters` hook, `ActiveFilterChips`, `MoreFiltersDisclosure`, `DateRangeField` |

Nothing already built is redesigned, replaced, or duplicated — every
addition above is either a new, small, focused component/hook or an
additive prop on an existing component that leaves current usage
unaffected when omitted (matching the pattern already established in
the coverage patch for `Sidebar`'s `mobileOpen`).

## Follow-up: the common list contract (search/filter/sort/pagination)

A second pass, prompted by actually wiring `UsersPage` up as a real
consumer of this layer rather than a second, separate hand-rolled
fetch. Re-audited against the "one Search/FilterBar/Sorting/Pagination
foundation, Users as the first real consumer" framing before touching
anything, per Engineering Principle §16.

**Already covered, no change** (the frontend half of this was mostly
right the first time):

- `DataTable`'s `sort`/`onSortChange` and `page`/`totalPages`/`total`/
  `onPageChange` were already controlled-by-the-caller, which is what
  "server-side sort/pagination" requires structurally — confirmed by
  actually wiring a real backend to them for the first time, not just
  by the shape being controlled.
- `FilterBar`, `ActiveFilterChips`, `MoreFiltersDisclosure`, `useFilters`
  — reused for `UsersPage`'s filter row as-is; no gap found on
  re-inspection.
- `SortableHeader`/`sort.ts`'s `SortState`/`toggleSort` — reused as-is.
- `useServerTable` existed but had never actually been exercised against
  a real endpoint (`UsersPage` originally bypassed it — see below).

**Genuine gaps found, now fixed:**

- **No backend endpoint returned a total, or supported sorting, at
  all.** `GET /api/users`/`GET /api/teams` used `skip`/`limit` and
  returned a bare array — `useServerTable`'s `{rows, total}` contract
  was structurally unsatisfiable by any real endpoint in this codebase
  until now. This was the actual reason `UsersPage` was originally
  built with a flat one-shot `limit=200` fetch instead of the hook that
  already existed for exactly this. Fixed with one standard envelope
  (`app/schemas/pagination.py`'s `PaginatedResponse` — `data` +
  `pagination{page,page_size,total,total_pages}`) and one shared
  primitive (`app/core/list_query.py`'s `paginate`/`apply_sort`),
  applied to both `GET /api/users` and `GET /api/teams` — proving the
  contract on two independent resources, not just one.
- **No safe way to sort by an arbitrary client-supplied field.**
  `apply_sort` maps an approved `sort_by` string to a real column via a
  fixed, per-endpoint dict (`_SORT_FIELDS` in each router) — an
  unrecognized key is a 422 naming the allowed set, never a fallback
  that silently ignores the request, and never a raw
  `order_by(getattr(Model, sort_by))` that would let a client order by
  (or, on some backends, probe the existence of) an arbitrary column
  such as `password_hash`.
- **`useServerTable` didn't reset the page on a sort change**, only on
  a filter change — the previous page number could point past the end
  of a freshly-resorted result set. Fixed; a matching gap for page-size
  (there was no way to change it at all) is fixed by the same change.
- **No stale-response protection.** Only an unmount guard existed; a
  slower, now-superseded request (e.g. from typing quickly into a
  search box) could still resolve after a newer one and overwrite
  fresher rows. Fixed with a request-id ref inside `useServerTable` —
  only the response matching the latest request is ever applied.
- **No way to refresh the current page after a mutation** (create,
  role change, activate/deactivate) without resetting page/sort/filters
  — `UsersPage` originally re-ran its own one-shot fetch by hand for
  this. `useServerTable` now exposes `refetch()` for exactly this case.
- **No reusable search debounce.** `UsersPage` had hand-rolled a
  `setTimeout`-based debounce inline. Extracted into
  `useDebouncedValue` — deliberately *not* a new `SearchField`
  component, since `TextField` (with its existing `leadingIcon`/
  `trailingSlot` props) already covers the "standard search input"
  shape; inventing an eleventh field type alongside the ten in
  `docs/modules/common_ui_components.md` would have duplicated it for
  no reason.
- **No standard page-size control.** `Pagination` gained optional
  `pageSize`/`pageSizeOptions`/`onPageSizeChange` props (and
  `DataTable` forwards them) — omitted, both behave exactly as before.

**Explicitly not built**, per the same spec's own list: a generic
query/filter-expression builder, saved filters, an advanced search
language, Elasticsearch/OpenSearch, infinite scrolling, a new
client-state framework, or a second table implementation.
`app/core/list_query.py` takes a page number and an already-validated
sort key, not an arbitrary expression — it is the same size and shape
as `app/core/search.py`'s `apply_keyword_filter`, not a query engine.

**Verification**: `UsersPage` is the first real consumer end to end —
search, sort (both directions), pagination (`Next`/`Previous`), and a
page-size change all confirmed against a live backend with 26 seeded
users, checking the actual request parameters sent for each
interaction (not just that something rendered), including that
changing page preserves the active sort and that changing sort/search/
page-size correctly resets to page 1. 16 new backend tests
(`tests/test_list_query.py`) cover the primitive standalone plus both
real endpoints; the existing `tests/test_users.py`/`test_teams.py`/
`test_search.py` suites were updated for the new response envelope,
not rewritten.
