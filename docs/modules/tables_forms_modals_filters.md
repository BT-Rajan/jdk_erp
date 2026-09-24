# JDK Common Tables / Forms / Modals / Filters

The next foundation layer on top of `docs/modules/common_ui_components.md`
— hardening the table, form, modal and filter primitives already built
there toward real module use (server-side data, row selection, bulk
actions, a fixed set of dialog patterns, and a standard filtering
system), not replacing them.

## Common Tables

One reusable table system across JDK.

Core capabilities: column definitions, sorting, search, filtering,
pagination, row selection where required, row action menu (⋮), status
badges, loading state, empty state, error state, responsive behaviour,
server-side pagination/sort/filter for large datasets.

Optional where genuinely needed: column visibility, bulk actions, row
expansion, sticky header.

Rules: one table implementation; no module-specific table copies; don't
fetch all records just to filter/sort in the browser; keep actions
consistent; bulk actions only when the workflow genuinely requires them.

## Common Forms

One standard form system for creating/editing records.

Field types: text, number, currency, date/date-time, select,
multi-select, search/autocomplete, checkbox, radio, textarea, file
upload.

Standard behaviour: labels, required indicators, help text where
useful, field-level validation, error messages, read-only/disabled
states, loading/submitting state, Save/Cancel actions, unsaved-change
warning where required.

Rules: UI validation for immediate feedback; server-side validation is
authoritative; business rules must not exist only in the UI; don't
create different form systems per module; large/complex workflows
should use pages rather than giant modals.

## Common Modals / Dialogs

Keep the set small: confirmation dialog (cancel/delete/approve/reject/
deactivate); form dialog (small, self-contained forms); detail
dialog/drawer (quickly viewing record information without leaving the
current page); alert/message dialog (important information, warnings,
errors).

Rules: no nested modals; don't put large workflows inside modals;
destructive actions require clear confirmation; use drawers where a
larger amount of detail needs to remain alongside the current context;
consistent title, actions, spacing and close behaviour.

## Common Filters

One standard filtering system for tables/lists.

Common filter types: search, date/date range, status, user/owner, team,
customer, supplier, category/type, other meaningful module-specific
fields.

Standard behaviour: clear indication of active filters, apply,
clear/reset, consistent layout, responsive filter layout, server-side
filtering for large datasets, preserve filter state where useful.

Rules: don't expose every database field as a filter; default filters
should reflect the actual workflow; keep commonly used filters
immediately accessible; advanced/less-used filters can be placed behind
a "More filters" control; filters must work consistently with sorting
and pagination.

## The relationship

Table → displays records. Filter → narrows records. Sort → orders
records. Form → creates/edits records. Modal/Dialog → handles focused
interactions. Drawer → provides contextual detail.

## Core principle

One shared implementation for each capability. Modules configure the
components; they do not recreate them. Keep the common layer powerful
enough for JDK, but small enough to remain predictable and fast.

## Implementation approach

See `docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md` for what's already
covered by the existing Common UI Components layer vs. genuinely new.

## Master data forms as pages

Every Master Data record's create/edit form (Categories, Units of Measure,
Customers, Suppliers, Products, Raw Materials, Production Lines, Machines,
Warehouses, Bills of Materials) is a page, not a dialog:
`/<master>/new` and `/<master>/:id/edit`. `FormPage`
(`components/ui/FormPage.tsx`) takes the same props as `FormDialog`;
`useFormRoute` (`lib/useFormRoute.ts`) drives it from the URL and hides
the list while the form is open. Edit from the list passes the row along;
a direct visit or refresh loads it from `GET /api/<master>/:id`. Cancel
and Save return to the list. Small secondary dialogs (confirmations,
supplier links, BOM components, customer assignment) stay dialogs.
