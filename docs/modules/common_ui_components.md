# JDK Common UI Components

One standard component library, reused by every module screen, so a
button, table, badge or modal looks and behaves identically everywhere
(Engineering Principles §6–7). This is the shared foundation every future
module's screens (Phase 2 Master Data onward) are built on top of — no
module builds its own button, table, or dialog.

## 1. Layout

- Page header
- Breadcrumb
- Section/card
- Tabs
- Standard spacing/grid

## 2. Actions

- Primary button
- Secondary button
- Danger button
- Icon button
- Action menu (`⋮`)
- Button loading/disabled states

## 3. Forms

- Text input
- Number input
- Date/date-time input
- Select
- Multi-select
- Search/autocomplete
- Checkbox
- Radio
- Textarea
- File upload

## 4. Data & Tables

- Table
- Column sorting
- Filtering
- Search
- Pagination
- Column visibility where needed
- Status badge
- Summary/stat card
- Key-value/detail view

## 5. Feedback & States

- Loading state
- Empty state
- Error state
- Success message
- Warning/alert
- Confirmation dialog

## 6. Overlays

- Modal/dialog
- Drawer/detail panel
- Tooltip where useful
- Visible context/action menu

## 7. Navigation

- Sidebar
- Top navigation where required
- Tabs
- Breadcrumb

## 8. Standard Data Display

- Currency
- Number
- Date/time
- Percentage
- Status/state
- User/person display

## Important exclusions

Do not make these universal UI components:

- Right-click menus
- Complex dashboards
- Special-purpose charts
- Module-specific workflow widgets
- Custom controls that duplicate existing components

## Core rule

One common component → one implementation → consistent behaviour
everywhere. Build new components only when the requirement is genuinely
common or the existing components cannot satisfy it.

## Implementation approach

See `docs/audit/COMMON_UI_COMPONENTS_AUDIT.md` for what's reused from
`jdk_clean` in shape vs. rebuilt, and why.
