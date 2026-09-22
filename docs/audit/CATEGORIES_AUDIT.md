# Categories Audit — `jdk_clean`

Phase 2 (Master Data) audit of the category/classification layer, per
[`../ROADMAP.md`](../ROADMAP.md) and the spec in
[`../modules/categories.md`](../modules/categories.md).

## Verdict

**Nothing to reuse.** Unlike Teams (`jdk_clean` had a real `Department`
entity worth partial reuse), Categories in `jdk_clean` is the Organisation
case again: no model, no table, no API, no service, no admin UI exists at
all. What exists instead is worse than nothing to reuse — a cautionary
example of exactly the failure mode this module exists to prevent.

## What's there

A free-text `category VARCHAR(100)` column, independently declared three
times with identical shape and no shared type, mixin, or constant between
them: `Product.category` (`backend/app/models/product.py:28`),
`RawMaterial.category` (`backend/app/models/raw_material.py:35`),
`Customer.category` (`backend/app/models/customer.py:116`). No foreign
key, no lookup table, no enum, no uniqueness, no normalization (no
`.strip()`, no case-folding) anywhere in `backend/app/crud/master_data.py`.
Only a plain exact-match filter (`WHERE category = :value`) on each
master's list endpoint, via `filterable_fields` in
`backend/app/crud/master_data.py:102,287,320`. No org/tenant scoping
either — consistent with this codebase having no organisation concept at
all (see [`ORGANISATION_AUDIT.md`](ORGANISATION_AUDIT.md)).

The frontend mirrors this: a plain `TextField` on each master's form
(`ProductFormPage.tsx`, `RawMaterialFormPage.tsx`, `CustomerFormPage.tsx`),
rendered as a `Badge` on each detail page, with **only Customers'** list
page exposing a filter for it — Products and Raw Materials don't surface
category in their lists at all, an inconsistency with no evident reason.

## Why this is not reused

The codebase's own comments explicitly defend this as a deliberate
choice — "not read by any business logic," "deliberately not a fixed
picklist," "no consumer anywhere in this app"
(`product.py:24-28`, `customer.py:111-116`) — but the same codebase
documents, in the very next model it defines, why that choice fails in
practice. `raw_material.py:10-19`'s comment on units of measure describes
exactly this: a units-of-measure lookup table was removed in favour of
free text, and free text "turned out to be the wrong call" — `"kg"` grew
`"Kg"`/`"KGS"` siblings with no relationship enforced between what a
packaging line recorded and what a material actually used. `category`
carries the identical risk today, uncorrected: three independent
free-text columns with no dedup, so `"VIP"`, `"vip"`, and `"VIP "` (or an
entirely accidental naming collision between a Product category and a
Customer category that happen to share a string) are indistinguishable to
the application and unrecoverable without a manual data-cleanup pass.
There is no hardcoded list, hierarchy, or hidden complexity to strip back
either — this is not an over-built system to simplify, it's the complete
absence of a system.

## Scope decision

Categories is built fresh in `jdk_erp` directly against
[`categories.md`](../modules/categories.md), the same way Organisation
was (see [`ORGANISATION_AUDIT.md`](ORGANISATION_AUDIT.md)) — reusing this
project's own Foundation primitives (`OrganisationScopedMixin`,
`app/core/list_query.py`, `app/core/search.py`, `app/services/audit_service.py`,
`require_admin`) rather than anything from `jdk_clean`, and structurally
mirroring `Team` (`docs/modules/teams.md`) — name/code/description/is_active,
no hierarchy — since nothing in either audit justifies a parent/child
category tree for JDK's small, flat category list. Unlike Team, Category
gets a full admin-gated create/edit/status API from the start (not
deferred to a later phase): RBAC already exists by the time this module
is built, so there is no "wait for an authorised Admin to be defined"
reason to leave it out, the way there was for Organisation's and Teams'
first passes.
