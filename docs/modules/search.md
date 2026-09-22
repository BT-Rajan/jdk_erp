# JDK Search

A foundation-layer *mechanism*, not a module of its own — every resource
that already has a `GET .../` directory endpoint (Users, Teams today;
Customers, Products, ... as Phase 2+ builds them) adds keyword search to
that same endpoint rather than exposing a second, parallel lookup path.
Depends on [`authentication.md`](authentication.md),
[`organisation.md`](organisation.md) and whichever module owns the
resource being searched (e.g. [`users.md`](users.md),
[`teams.md`](teams.md)) — search adds nothing to what those modules
already enforce.

## 1. Purpose

Search must never become a data-discovery backdoor. The moment a keyword
box can surface a record a plain list of that same resource wouldn't
have shown, authorization has been bypassed — the query changed, the
rules that scope it did not follow.

```text
User
 ↓
Authentication
 ↓
Organisation / role / team / ownership scope
 ↓
Search query
 ↓
Only records that scope already permits
```

## 2. Core rule

> Search is another read operation, not a privileged data-access
> mechanism. Every keyword search, autocomplete, and future global
> search must enforce the exact same authorization and data-scope rules
> as the plain list endpoint for that resource — because it *is* that
> endpoint, with one more filter appended, never a separate code path.

## 3. Mechanism: narrow, never widen

A resource's list endpoint already builds a fully-scoped query (today:
`User.organisation_id == current_user.organisation_id`, active-only by
default, plus whatever role/team/ownership filters that module's own
spec requires). Search takes that exact `Query` object — after every
other filter has already been applied to it — and appends one more `AND`
predicate over that resource's own searchable columns
(`app/core/search.py`'s `apply_keyword_filter`). A blank/missing keyword
is a no-op (the plain, already-authorized list); it is never treated as
"match everything," and it can only ever remove rows from what the
caller could already see, never add one.

This is what makes the anti-backdoor property true by construction, not
by convention: there is no second query-building path with its own
(potentially drifted) scope for search to get wrong. `GET /api/users?q=`
and `GET /api/users` run the same base query.

## 4. No separate search-permission system

Do not invent a parallel `can_search(user, resource)` gate. A resource's
searchability is exactly its existing read-authorization —
`GET /api/users` is open to any authenticated organisation member today
(`docs/modules/users.md`); `q=` on that same endpoint inherits that,
nothing more, nothing less. When a future resource's list endpoint is
role/team/ownership-gated, its search inherits that gate the same way,
automatically, because it's the same query.

## 5. No leakage

An unauthorized record must not be revealed by a keyword search any more
than by a plain list — not its name, id, existence, or a "found but you
can't see it" message. A query for a real record outside the caller's
scope returns an empty result, indistinguishable from a keyword that
matches nothing at all.

## 6. Autocomplete is the same mechanism, not an exception

An autocomplete/typeahead field (e.g. a future customer picker on a
quotation form) calls the same authorized search endpoint as the list
page's search box. It never gets its own lighter-weight, unauthenticated,
or unscoped lookup route "since it's just a suggestion."

## 7. Each module owns its own searchable columns

The mechanism (`apply_keyword_filter`) is generic; which columns it's
called with is a per-module decision, made once, in that module's own
list endpoint — `full_name`/`email`/`username` for Users, `name`/`code`
for Teams. A future module documents its own choice the same way.

## 8. Global search — deferred

A single "search everything" box only makes sense once there are enough
distinct resource types to justify it, and even then it must fan out to
each resource's own already-scoped query (§3) — never a cross-table
free-text index that bypasses per-resource scope to get a single result
set. Not built now: Phase 2 (master data) hasn't landed yet, so there is
exactly one directory-style resource pair (Users, Teams) for it to
search across, which is what having it on each resource's own endpoint
already covers.

## 9. Performance

- Database-side filtering (`ILIKE`/equivalent), not fetch-then-filter in
  application code or the browser.
- Keyword length is capped at the API boundary (100 chars) — a guard
  against a pathological pattern, not a UX limit anyone should hit.
- `%`/`_` (SQL `LIKE`'s own wildcard characters) are escaped before the
  query runs, so a search for a literal `50%` matches only that text,
  never acts as a pattern.
- Existing pagination (`skip`/`limit`) and the existing
  `(organisation_id, is_active)` index continue to apply unchanged —
  search adds a predicate to an already-indexed, already-paginated
  query, not a new unindexed scan.
- No Elasticsearch/OpenSearch or other external search engine — not
  needed at this scale, and it would need its own authorization sync
  with the database (see §4) to avoid drifting from RBAC.
- Debouncing an autocomplete/typeahead input is the frontend's job (a
  plain `setTimeout`-based debounce is enough today; no shared hook
  exists yet because there's only one call site).

## 10. Acceptance tests

1. A keyword matching a record inside the caller's own organisation is
   returned.
2. The identical keyword, matching a real record in another
   organisation, returns nothing — not an error, not a "no access"
   result, an empty list indistinguishable from "no match."
3. A keyword matching an inactive record is excluded by default, exactly
   as the plain list already excludes it (`include_inactive` still
   overrides it, identically for search and plain list).
4. Search is case-insensitive.
5. A blank/missing keyword returns the same result as the plain list
   with no `q` at all.
6. A literal `%` or `_` in the keyword is not treated as a SQL wildcard.
7. A keyword longer than the length cap is rejected (422), not silently
   truncated.
8. No endpoint exposes a keyword-search parameter without also applying
   that resource's own organisation/role/team scope — i.e. there is no
   "search" code path that skips the filters its own plain list applies.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §2
("one reusable implementation for common functionality") and §5 ("reuse
before creating"): `app/core/search.py`'s `apply_keyword_filter` is the
one mechanism, added to both of today's real call sites in the same
change so it's proven against two resources, not built speculatively
against zero.

**Implemented now:**

- `app/core/search.py`: `apply_keyword_filter(query, keyword, *columns)`
  — case-insensitive, `%`/`_`-escaped, blank-keyword-is-a-no-op. Uses
  each column's own `.ilike()` (portable across SQLite and MySQL,
  this project's two supported databases) rather than a
  database-specific `ILIKE` operator.
- `GET /api/users?q=...` — searches `full_name`, `email`, `username`,
  applied after the existing organisation/`is_active`/`team_id` filters
  in `list_users` (`app/api/users.py`).
- `GET /api/teams?q=...` — searches `name`, `code`, applied after the
  existing organisation/`is_active` filters in `list_teams`
  (`app/api/teams.py`).
- Tests proving acceptance criteria 1-7 against both endpoints,
  including the cross-organisation and inactive-record isolation checks
  that are the actual security property this document is about, not
  just "the LIKE clause matches."

**Deferred, not forgotten:**

- **Global search** (§8) — no second/third master-data resource exists
  yet (Phase 2 hasn't been built) to make a single search box meaningful
  across resource types; revisit once it does.
- **Autocomplete** (§6) — no form yet needs a live-lookup picker (no
  Customer/Product/etc. exists to pick from); when one does, it calls
  the resource's own `q=` endpoint, not a new one.
- **Full-text ranking/relevance scoring** — a plain substring match is
  sufficient at today's scale (§9); revisit only if a real module's data
  volume and query patterns actually need it.
