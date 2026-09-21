# Design System

Visual foundation for the standard UI system required by
[`ENGINEERING_PRINCIPLES.md`](ENGINEERING_PRINCIPLES.md) §6–7: one
implementation, one visual behaviour, for every button, form, table, badge
and status colour across every module.

This is inspired by the previous JDK ERP's "Obsidian & Champagne" theme —
a dark, premium look with gold accents — carried forward as a starting
point, not copied code. Tune the exact values once real screens are built,
then treat this file as the source of truth and update it in the same PR.

## Typography

| Role                          | Font              | Weights       |
| ------------------------------ | ----------------- | ------------- |
| Display (page titles, hero)    | Playfair Display  | 500, 600      |
| Body / UI (everything else)    | Inter             | 400, 500, 600, 700 |

Playfair Display is reserved for large display type — page headings, the
login screen, key figures on dashboards. Every control, table, form and
body of text uses Inter. Don't mix in a third typeface.

## Colour palette

Base neutrals ("ink") and the primary accent ("gold/champagne") form the
core palette. Dark theme by default (`color-scheme: dark`).

| Token          | Hex       | Use                                   |
| -------------- | --------- | -------------------------------------- |
| `ink-950`      | `#05050a` | App background                         |
| `ink-900`      | `#0b0b12` | Surface / panel background             |
| `ink-800`      | `#12121c` | Raised surface                         |
| `ink-700`      | `#1a1a28` | Border / divider on dark surfaces      |
| `ink-600`      | `#262638` | Muted surface, disabled states         |
| `gold-100`     | `#faf3e2` | Text on gold, lightest tint            |
| `gold-200`     | `#f1d999` | Hover highlight                        |
| `gold-300`     | `#e4c37e` | Secondary accent                       |
| `gold-400`     | `#d4af6a` | **Primary accent** — buttons, links, focus rings |
| `gold-500`     | `#c39a4e` | Accent hover                           |
| `gold-600`     | `#b9873c` | Accent active/pressed                  |
| `gold-700`     | `#8f6a2c` | Accent text on light backgrounds       |
| `violet-500`   | `#6a4fb3` | Secondary accent (sparingly — a second signal, not a competing brand colour) |
| `violet-600`   | `#4c3480` | Secondary accent hover                 |

### Status colours — one set, used everywhere

The previous frontend picked ad hoc Tailwind colours per page (emerald,
rose, amber, sky — different shades in different modules for the same
meaning). That is exactly the duplication Principle 6 forbids. This
project defines status colour **once**, here, and every badge, alert and
status indicator uses it — no per-module variants:

| Status    | Token         | Hex       | Meaning                                  |
| --------- | ------------- | --------- | ----------------------------------------- |
| Success   | `success-500` | `#22c55e` | Completed, approved, in stock, paid       |
| Warning   | `warning-500` | `#f59e0b` | Needs attention, pending, low stock       |
| Danger    | `danger-500`  | `#f43f5e` | Rejected, overdue, blocked, error         |
| Info      | `info-500`    | `#38bdf8` | Informational, in progress, draft         |
| Neutral   | `ink-600`     | `#262638` | Not started / not applicable              |

A given business state (e.g. "Quotation: Accepted") always maps to the
same status colour everywhere it appears — dashboard, list, detail page.

## Elevation & surfaces

The old theme used a frosted-glass look (`backdrop-filter: blur()` panels
over a dark background) for cards, headers and modals. Reuse the idea, but
implement it once as a shared UI primitive (e.g. a `Panel`/`Card`
component) — not copy-pasted CSS per page.

## Accessibility

- Focus is always visible: a 2px `gold-400` outline on every interactive
  element, never suppressed (`:focus-visible`).
- Don't rely on colour alone for status — pair colour with text/icon
  (e.g. a badge reads "Overdue", not just red).
- Verify text/background contrast against `ink-950`/`ink-900`, especially
  for `gold-500`+ on dark and any text placed on `violet-500`.

## Implementation notes

- If the frontend uses Tailwind v4, define these as `@theme` tokens (as
  the previous app did) so utilities like `bg-ink-900`, `text-gold-400`,
  `font-display` are generated directly — no hard-coded hex values in
  components.
- Status colours belong to the shared Badge/Alert/StatusDot components
  from day one of Phase 1, not added ad hoc as modules are built.
