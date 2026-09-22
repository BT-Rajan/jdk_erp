# Common Validation — Audit

Audit of what already exists in `backend/` and `frontend/` against
`docs/modules/common_validation.md`, before adding anything. This module
is built ahead of the business modules that will consume it (Sales,
Finance, Products, Materials — none exist yet), the same way the UI
layer was built ahead of Phase 2 — so most of the checklist has no
concrete caller yet; each utility is still fully implemented and tested
on its own, following the precedent already set for `authorization_service`
and `useServerTable`.

## Already present

- **`email-validator>=2.2`** is already a backend dependency
  (`backend/requirements.txt`), and Pydantic's `EmailStr` (which it
  backs) is already used for format checking in
  `app/schemas/user.py`'s `email` field. Reused directly — via the same
  `email_validator` package `EmailStr` already depends on — for the new
  standalone `validate_email_format`/normalization helpers, instead of
  hand-writing a second regex-based check.
- **`Organisation.currency`** (`String(3)`) and **`Organisation.timezone`**
  (`String(64)`, default `"UTC"`) already exist
  (`backend/app/models/organisation.py`) — Organisation was already
  designed to carry per-organisation currency/timezone configuration.
  "Central KWD configuration" and "the established JDK/Kuwait timezone"
  mean *changing what these already-existing fields default to*, not
  adding new ones.
- **react-hook-form + zod** are already wired end to end (verified by
  `frontend/src/components/forms/formIntegration.test.tsx` from the
  previous phase) — "frontend validation improves usability" already
  has its one mechanism; this module adds JDK-specific schema pieces
  (email domain, ID formats, date-range) to that existing mechanism,
  not a second one.
- `backend/app/core/validation.py` already has `validate_password_complexity`
  and `validate_key` — reused as-is, extended in place rather than
  replaced.
- `Currency`/`CurrencyField`/`formatCurrency` (frontend) and
  `AccessDeniedState`/`PageErrorState` (backend error-contract mirrors)
  already exist from prior phases — reused, only their *defaults*
  change here (see below).

## Genuine gaps / corrections

- **No company-email-domain check anywhere.** `Organisation` has no
  domain field at all — a new nullable `email_domain` column is needed
  (nullable: an organisation that hasn't configured one simply doesn't
  get the domain restriction, matching "domain is configuration, not
  hard-coded" — it isn't mandatory configuration).
- **No date-range comparison helper, backend or frontend.** Every
  "from ≤ to" check would currently be hand-written per call site.
- **No ID-format registry.** Quotation/Order/User/Product/Material ID
  shapes (`QXXXXXX`, `OXXXXXX`, `XXXXX`, `PRXXXX`, `MXXXX`) have no
  code representation yet — needed as a shared, generic
  prefix+digit-count validator/generator so a future module doesn't
  invent its own regex per entity.
- **No currency-decimal/rounding utility.** Nothing enforces "KWD's 3
  decimal places, `Decimal` arithmetic, consistent rounding" anywhere —
  a future module doing money math would use plain `float` by default
  (the exact anti-pattern the spec is written to prevent).
- **No centralized timezone utility.** `datetime.utcnow()`/naive
  datetimes are used throughout the existing auth/session code (correct
  for storage), but there's no single `to_jdk_time()` a future
  display/report layer would call — without one, "do not allow
  individual modules to implement their own timezone conversion" has no
  way to be enforced.
- **No QR generation or domain validation at all.** Zero code, zero
  dependency, in either backend or frontend.
- **Frontend date format doesn't match this spec.** `lib/format.ts`'s
  `formatDate`/`formatDateTime` render `DD-MM-YYYY` (hyphens) — this
  module explicitly specifies `DD/MM/YYYY` (slashes) as the standard
  user-facing format. This is a correction, not a new feature: the
  earlier phase never had an explicit separator specified by the user,
  the display convention (`docs/DESIGN_SYSTEM.md`) never mentioned dates,
  and this module now sets that standard explicitly — the separator
  changes to match it. Internal storage (ISO datetimes over the API) is
  untouched; only the display string changes.
- **KWD/USD default currency is backend-and-frontend inconsistent with
  the new standard.** `Organisation.currency` has no Python default
  (must always be supplied); `frontend`'s `Currency`/`CurrencyField`
  default to `'USD'`. Both become `'KWD'` — the org can still override
  per-organisation (the field/prop still take any ISO code), this only
  changes what happens when nothing is specified, matching "JDK
  standard currency: KWD."
- **`Organisation.timezone`'s default is `"UTC"`, not Kuwait.** Changes
  to `"Asia/Kuwait"` for the same reason.

## What's added

| Area | Added |
| --- | --- |
| Backend `app/core/validation.py` | `normalize_email`, `validate_email_format` (via `email-validator`), `validate_company_email_domain`, `validate_date_range` |
| Backend `app/core/id_formats.py` | `IdFormat` (prefix + digit count, `.validate()`/`.format()`), `QUOTATION_ID`/`ORDER_ID`/`USER_ID`/`PRODUCT_ID`/`MATERIAL_ID` |
| Backend `app/core/currency.py` | `DEFAULT_CURRENCY = "KWD"`, `CURRENCY_DECIMALS`, `round_currency()` (`Decimal`, `ROUND_HALF_UP`) |
| Backend `app/core/timezone.py` | `JDK_TIMEZONE` (`Asia/Kuwait`), `now_jdk()`, `to_jdk_time()` |
| Backend `app/core/qr.py` | `validate_qr_url()` (HTTPS + allowed-domain), `generate_qr_code()` (optional branded logo overlay) |
| Backend model | `Organisation.email_domain` (new nullable column + migration); `currency` default → `KWD`; `timezone` default → `Asia/Kuwait` |
| Backend config | `ALLOWED_QR_DOMAINS` setting |
| Frontend `lib/format.ts` | Date separator `-` → `/` |
| Frontend `lib/currency.ts` | `DEFAULT_CURRENCY`, `CURRENCY_DECIMALS`, `currencyDecimals()` — shared by `CurrencyField`'s step default and the new defaults below |
| Frontend `lib/validation.ts` | `normalizeEmail`, `companyEmailDomain` zod refinement, `dateRange` zod refinement, ID-format regexes matching the backend patterns exactly |
| Frontend `lib/timezone.ts` | Kuwait-timezone-aware `formatKuwaitTime()` |
| Frontend defaults | `Currency`/`CurrencyField` default `currency` → `KWD` |

## Deliberately not built now

- **No live email-domain/duplicate-email enforcement wired into an
  endpoint.** There is no user-creation endpoint yet (Users only
  supports read + admin role-change — "still excludes create/edit" per
  `docs/audit/USERS_AUDIT.md`), so there is no real caller to wire this
  into. The validators are fully implemented and tested standalone,
  ready for whichever module adds user creation.
- **No Quotation/Order/Product/Material tables or ID-generation
  wired to a sequence.** `IdFormat.format()` takes a sequence number as
  a plain argument — the future module that owns the actual table
  supplies "the next number" (e.g. from its own row count or a
  dedicated sequence); this module only owns the *shape*, not where the
  number comes from, matching the spec's own boundary ("common
  validation provides the mechanism, the module provides the business
  rule").
- **No past/future date restriction anywhere.** The spec is explicit
  that this is a business rule ("the actual business module determines
  whether past/future dates are allowed") — only the `From ≤ To`
  mechanism is common.
