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

  `src/pages/StyleGuidePage.tsx` (routed at `/styleguide`) is a
  kitchen-sink demo composing every component on one page — useful as a
  quick visual reference and as a live smoke test (`npm run dev`) until
  real module screens make it redundant.

- **Common UI Components — coverage patch** (same directories) — a
  follow-up pass that audited the phase above and added only what was
  genuinely missing, per
  [`../docs/audit/COMMON_UI_COMPONENTS_COVERAGE_PATCH.md`](../docs/audit/COMMON_UI_COMPONENTS_COVERAGE_PATCH.md):
  - **Charts** (`src/components/charts/`): `LineChart`, `BarChart`
    (`stacked` variant), `PieChart` (`donut` variant), built on
    `recharts` (matching `jdk_clean`'s own choice) through one shared
    `ChartState` wrapper for loading/empty/error — modules never import
    `recharts` directly. KPI is covered by the existing `StatCard`, not
    duplicated.
  - **Context menu**: `ContextMenu` (right-click, desktop-only
    convenience), always paired with the existing `ActionMenu` on the
    same row offering identical options, never a replacement for it.
    Shares a new internal `MenuPanel` with `ActionMenu` rather than
    duplicating the option-list/keyboard-nav logic a second time.
  - **Responsive fixes**: `DataTable` gained a per-column `hideBelow`
    breakpoint (drops a secondary column instead of forcing a scroll);
    `Sidebar` gained an off-canvas mobile mode (`mobileOpen`/
    `onMobileClose`, backward compatible); `Tabs` scrolls horizontally
    instead of overflowing; `TopNav`'s inline nav list now hides below
    `md` (a real overflow bug live-viewport testing caught, not
    something a code read alone would have found); new `StatGrid` for a
    responsive row of `StatCard`s.
  - **New utility/display components**: `CopyToClipboard`, `ProgressBar`,
    `Skeleton`, `AccessDeniedState` (mirrors the backend's
    `ACCESS_DENIED` contract), `PageErrorState` (mirrors the backend's
    generic `SERVER_ERROR` message), `useUnsavedChangesGuard` (tab-close/
    refresh warning only — in-app route blocking needs a data router
    this app doesn't use yet, documented as a deliberate deferral).
  - `recharts` is isolated into its own `vendor-charts` build chunk
    (`vite.config.ts`) so the main app bundle size is unchanged.

- **Tables / Forms / Modals / Filters** (same directories) — a
  harden-and-extend pass on top of the two phases above, per
  [`../docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md`](../docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  Nothing already built was redesigned; every addition is either a new
  component/hook or an additive, backward-compatible prop.
  - **Tables**: `DataTable` gained row selection (`selectable`/
    `selectedKeys`/`onSelectionChange`, with a header checkbox that goes
    indeterminate for a partial selection) and an opt-in `stickyHeader`;
    new `BulkActionsBar` (pairs with selection, renders nothing when
    nothing's selected); new `useServerTable` hook (`src/lib/`) — the
    one shared page/sort/filter-to-request wiring, so "don't fetch all
    records just to filter/sort in the browser" has an actual reusable
    answer instead of every module reinventing it.
  - **Forms**: `CurrencyField` (a currency-symbol-prefixed numeric
    field, distinct from `NumberField` per the spec's own field-type
    list); a required-field indicator across every field, and a
    `readOnly` style in `inputClasses` — **deliberately visual only**:
    `required` never sets the native HTML `required` attribute, because
    the browser's own constraint validation fires on submit and
    silently blocks it before react-hook-form's `handleSubmit` (and the
    zod resolver) ever runs — a real bug this caught while integrating
    the two, not a hypothetical one; new `FormActions` (the Save/Cancel
    row every form ends with, `formId` prop for a Save button that
    lives outside its `<form>`, e.g. in a dialog's footer); an
    integration test (`formIntegration.test.tsx`) proving
    react-hook-form + zod + these fields work together end to end,
    including field-level error display and a blocked submit while
    invalid.
  - **Modals**: `FormDialog` (for small, self-contained forms — Save
    lives in `Modal`'s footer, associated with the body's `<form>` via
    the native `form` attribute rather than nesting one inside the
    other) and `AlertDialog` (a single-button acknowledgement dialog for
    "important information, warnings and errors," distinct from
    `ConfirmDialog`'s two-button decision shape). `Drawer` already
    covered "detail dialog/drawer" and `ConfirmDialog` already covered
    "confirmation dialog" — reused as-is, no new code for either.
  - **Filters**: `useFilters` hook (`src/lib/`) — one shared way a
    module owns its filter-values state, active-filter counting, and
    apply/clear semantics; `ActiveFilterChips` (a scannable, individually
    removable summary of what's currently applied); `MoreFiltersDisclosure`
    (keeps advanced/less-used filters collapsed until asked for); new
    `DateRangeField` (a from/to pair — the spec lists "date/date range"
    as one filter type, and only a single-date field existed before).
  - **Common Validation** (docs/modules/common_validation.md): the
    frontend's copy of the same mechanisms as the backend's
    `app/core/` modules, for UI-side validation ahead of the server's
    authoritative check.
    - `formatDate`/`formatDateTime` (`lib/format.ts`) now render
      `DD/MM/YYYY`/`DD/MM/YYYY HH:mm` with slashes, matching the spec's
      standard display format (was hyphens).
    - `lib/currency.ts`: `DEFAULT_CURRENCY` (`KWD`) and
      `CURRENCY_DECIMALS`, mirroring the backend's
      `app/core/currency.py` — `Currency` and `CurrencyField` now
      default to KWD, and `CurrencyField`'s numeric `step` matches the
      given currency's own decimal precision instead of a hard-coded
      2-decimal assumption.
    - `lib/validation.ts`: `normalizeEmail`, `validateCompanyEmailDomain`,
      `validateDateRange`, and the same five `ID_FORMATS` shapes
      (Quotation/Order/User/Product/Material) as the backend's
      `id_formats.py` — plain functions a form's zod schema can wrap in
      `.refine()`.
    - `lib/timezone.ts`: `formatKuwaitTime` — the one JDK/Kuwait
      timezone conversion path; no component does its own.

- **Frontend integration layer** (`src/lib/apiClient.ts`, `src/lib/auth/`,
  `src/components/routing/`, `src/components/layout/AppLayout.tsx`,
  `src/pages/LoginPage.tsx`, `src/pages/DashboardPage.tsx`) — the piece
  that turns the component library above and the backend's auth API
  (`docs/modules/authentication.md`) into a running app, so this stays
  the one place a future module wires in rather than each rebuilding
  it:
  - `lib/apiClient.ts`: one `axios` instance every module calls through.
    Attaches `Authorization: Bearer <token>` on every request; on a 401
    it refreshes once (concurrent 401s share a single refresh call,
    since `POST /api/auth/refresh` rotates the refresh token on use)
    and retries the original request, or clears storage and signals
    `AuthProvider` if the refresh itself fails. `/api/auth/login` and
    `/api/auth/refresh` are exempt from this retry so a genuine bad
    password reaches the caller as the backend's own message, not a
    swallowed "session expired." Every rejection is an `ApiError`
    (`.message`, `.code`, `.fields`) built from the backend's one error
    envelope (`docs/modules/api_error_handling.md`) — never a raw axios
    error.
  - `lib/auth/tokenStorage.ts`: the one place tokens are read from /
    written to `localStorage` (see the file's own comment for the
    httpOnly-cookie tradeoff this accepts).
  - `lib/auth/AuthContext.tsx`: `AuthProvider`/`useAuth` — current user,
    `login()`, `logout()`, and session rehydration from
    `GET /api/auth/me` on load.
  - `components/routing/RequireAuth.tsx`: client-side route guard
    (usability only, per Principle 3 — the backend is the real
    boundary); redirects to `/login`, preserving the originally
    requested path so login returns the user there.
  - `components/layout/AppLayout.tsx`: composes `TopNav` + `Sidebar` +
    a routed `<Outlet/>` into the one authenticated app shell. A module
    adds a `<Route>` in `App.tsx` and a nav entry here — not a new
    layout.
  - `App.tsx` is now the real route table (`/login` public, everything
    else behind `RequireAuth`) rather than the kitchen sink itself —
    see `StyleGuidePage.tsx` above.

  Copy `frontend/.env.example` to `.env.local` and set `VITE_API_URL`
  before running `npm run dev` against a real backend.

- **Users** (`src/pages/UsersPage.tsx`) — the first consumer of the RBAC
  endpoints `roles_rbac.md` built with no UI at all until now
  (`docs/modules/users.md`). Admin-only: list every user in the
  organisation, create one (with role and initial team assignment via
  `POST /api/users`), change role, and activate/deactivate
  (`PATCH /api/users/{id}/role` / `/status`) from a row's action menu.

- **Email settings** (`src/pages/EmailSettingsPage.tsx`) — the frontend
  for `backend/app/api/communication.py`'s mailbox endpoints. A form for
  the organisation's mailbox (provider picker that autofills
  host/port/encryption from `GET /api/communication/email/providers`,
  IMAP/POP3 fields shown based on the chosen incoming protocol, SMTP
  fields, a password field that keeps the saved one when left blank and
  a checkbox to explicitly clear it instead), plus two independent
  checks below it: **Test connection** (opens/closes a real connection,
  never sends anything) and **Send test email** (actually sends one
  through the saved mailbox — proves the whole pipeline, not just that
  the credentials open a socket).

  Both admin screens above are nav-gated under a **Settings** group in
  `AppLayout.tsx` (`lib/auth/roles.ts`'s `isAdminRole`) — usability only,
  per Principle 3; a non-admin who reaches either route directly sees
  `AccessDeniedState` instead, since every call still goes through the
  same admin-gated backend endpoints.

- **Notifications** (`src/components/ui/NotificationBell.tsx`) — the one
  standard notification UI every module's `notify()` call surfaces
  through (`docs/modules/notifications.md`), not a per-module widget.
  Sits in `TopNav`'s actions slot next to the account menu: an unread
  badge (polled every 30s from `GET /api/notifications/unread-count`,
  not a push connection), a dropdown list, mark one/mark all read, and
  clicking a notification navigates to its `target_url` if it has one.
  No admin gate — every user has their own notifications, scoped
  entirely server-side to `recipient_user_id == current_user.id`.

- **Organisation settings** (`src/pages/OrganisationSettingsPage.tsx`) --
  the frontend for `backend/app/api/organisations.py`'s new edit/status
  endpoints (`docs/modules/organisation.md` #6). Admin-only: view and
  edit the organisation's own record (name, code, contact details,
  address, company email domain, currency, timezone) via a plain form,
  and activate/deactivate it below via a `Badge` + a danger `Button`
  behind a `ConfirmDialog` -- the same activate/deactivate shape
  `UsersPage` already uses, not a new pattern. The confirm dialog spells
  out the real consequence in plain language (every user, the acting
  admin included, is signed out immediately and reactivating is an
  operator action, not something this page can undo), since deactivating
  an organisation is a strictly bigger blast radius than deactivating
  one user. Deliberately minimal per that module's own "not a
  tenant-management framework" principle -- no dashboard, no hierarchy,
  no branch/subsidiary management. Nav-gated under **Settings** next to
  Users and Email, same admin check. 7 tests
  (`OrganisationSettingsPage.test.tsx`): access-denied, load, load
  error, save (request payload + re-render from the response), a
  server-side field conflict surfacing on the right field, and the full
  deactivate confirm-then-call-then-badge-updates flow plus its error
  path. Verified live: edit + save, an invalid-timezone validation error
  rendering inline, and deactivating actually invalidating the acting
  admin's own session (`GET /api/auth/me` and a fresh login both 401
  immediately after) against a real backend.

- **Common list contract** -- `UsersPage` as the first real consumer of
  `useServerTable` end to end, per the follow-up section in
  [`../docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md`](../docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  The hook existed but had never been wired to a backend that returned a
  total or supported sorting, so `UsersPage` had originally bypassed it
  with a flat one-shot `limit=200` fetch. `useServerTable` gained:
  page reset on sort change (previously only filter changes reset the
  page) and a matching `setPageSize` (there was no way to change it at
  all); a request-id-ref stale-response guard, so a slower, now-
  superseded request (e.g. from typing quickly into search) can no
  longer overwrite fresher rows; `refetch()`, so a mutation (create,
  role change, activate/deactivate) can refresh the current page without
  resetting page/sort/filters. New `useDebouncedValue` hook (`src/lib/`)
  replaces a hand-rolled `setTimeout` debounce that used to live inline
  in `UsersPage` -- deliberately not a new `SearchField` component, since
  `TextField`'s existing `leadingIcon`/`trailingSlot` props already cover
  the "standard search input" shape. `Pagination` gained optional
  `pageSize`/`pageSizeOptions`/`onPageSizeChange` props (`DataTable`
  forwards them) for a standard page-size control; omitted, both behave
  exactly as before. Verified against a live backend with 26 seeded
  users -- search, sort (both directions), pagination, and a page-size
  change all checked against the actual request parameters sent,
  including that changing page preserves the active sort. 11 new tests
  (`UsersPage.test.tsx`) plus hardening tests added to
  `useServerTable.test.ts`/`Pagination.test.tsx`.

- **Categories** (`src/pages/CategoriesPage.tsx`) -- the frontend for
  `backend/app/api/categories.py`, the first module of Phase 2 (Master
  Data, `docs/modules/categories.md`), composed exactly like `UsersPage`:
  `DataTable` + `FilterBar` + `useServerTable` + `useDebouncedValue` for
  the list, `FormDialog` for create/edit, `ConfirmDialog` for
  activate/deactivate. Nav-gated under a new **Master Data** group in
  `AppLayout.tsx` -- deliberately in the general nav, not the admin-only
  `ADMIN_NAV_ENTRIES` group Settings uses, since reading the category
  list is open to any authenticated organisation member (only the
  mutating actions are admin-gated). `isAdminRole(currentUser?.role)`
  hides the New Category button, the row action menu, and the
  form/confirm dialogs for a non-admin -- a usability courtesy on top of
  the real server-side boundary, not the enforcement itself; a non-admin
  still sees the full list, including inactive categories. 10 new tests
  (`CategoriesPage.test.tsx`): load, the non-admin read-only view (list
  renders, no mutating controls), error state, empty-vs-no-match states,
  debounced search, create (success and a server-side name conflict
  surfacing as a form error), edit (pre-filled form, PATCH), and
  deactivate (confirm-then-call, plus its error path).

- **Units of Measure** (`src/pages/UnitsOfMeasurePage.tsx`) -- the
  frontend for `backend/app/api/units.py`
  (`docs/modules/units_of_measure.md`), composed identically to
  `CategoriesPage` and nav-gated alongside it under **Master Data**. No
  conversion UI of any kind (see the module's own audit -- jdk_clean
  tried that once and removed it). The Code field's hint text ("Stored
  upper-case") reflects the backend's normalization rather than
  duplicating it client-side. 10 new tests
  (`UnitsOfMeasurePage.test.tsx`), same coverage shape as
  `CategoriesPage.test.tsx`.

- **Customers** (`src/pages/CustomersPage.tsx`) -- the frontend for
  `backend/app/api/customers.py`
  (`docs/modules/customers.md`/`docs/audit/CUSTOMERS_AUDIT.md`), the
  first master-data page with a real ownership/visibility model rather
  than a flat admin/everyone split. Composed from the same list
  foundation as `CategoriesPage`/`UnitsOfMeasurePage`
  (`DataTable`/`FilterBar`/`useServerTable`/`useDebouncedValue`/
  `FormDialog`/`ConfirmDialog`/`ActionMenu`), but never re-implements
  visibility client-side -- the backend already returns only the rows
  the caller's resolved scope permits, so this page just renders
  whatever it receives. Any authenticated user can create a customer;
  the Edit/Deactivate actions render only for an admin and Assign only
  for an admin or manager (`isAdminRole`/`role === 'manager'`) -- a
  usability courtesy on top of the real server-side gate, not the
  enforcement itself. The Assigned-To column resolves a name via the
  existing organisation-wide `GET /api/users` (only fetched for
  admin/manager, who are the only roles with an Assign action to use it
  for) rather than a new lookup endpoint. 13 new tests
  (`CustomersPage.test.tsx`): load, assignee-name resolution, role-based
  action visibility (team_member sees none, manager sees Assign only,
  admin sees all three), error state, debounced search, create, edit,
  deactivate, and assign (including explicitly un-assigning). Verified
  live with four real users (admin, manager, and two salespeople) against
  a real backend: each saw exactly the customers their resolved
  OWN/TEAM/ALL scope predicts, and assign/deactivate actions updated the
  list correctly.

- **Suppliers** (`src/pages/SuppliersPage.tsx`) -- the frontend for
  `backend/app/api/suppliers.py`
  (`docs/modules/suppliers.md`/`docs/audit/SUPPLIERS_AUDIT.md`),
  deliberately the lightest master-data page so far (~10 records per
  organisation expected). Composed identically to `CategoriesPage` --
  the same flat admin-gated shape (`isAdminRole` hides New Supplier, the
  row action menu, and the form/confirm dialogs for a non-admin), not
  `CustomersPage`'s ownership/assign machinery, since a supplier has no
  assignment dimension at all. The create/edit form fields mirror
  `CustomersPage`'s contact-field shape (name/contact_person/phone/
  email/address) instead. 10 new tests (`SuppliersPage.test.tsx`), same
  coverage shape as `CategoriesPage.test.tsx`: load, non-admin read-only
  view, error state, empty-vs-no-match states, debounced search, create
  (success and a server-side name conflict surfacing as a form error),
  edit (pre-filled form, PATCH), and deactivate. Verified live against a
  real backend: creating a supplier showed the auto-generated `SUP0001`
  code and digits-only-normalized phone immediately, a duplicate name
  surfaced its 409 inline, a team_member saw the same list with no
  mutating controls, and deactivating updated the status badge.

## Setup

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint
npm run test       # vitest + @testing-library/react
```
