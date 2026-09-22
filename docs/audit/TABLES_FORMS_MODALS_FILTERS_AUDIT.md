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
