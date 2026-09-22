/** Mirrors backend/app/core/validation.py and id_formats.py -- the
 * frontend's copy of the same mechanisms, for UI-side validation (zod
 * schemas, inline field checks) ahead of the server's authoritative
 * check (docs/modules/common_validation.md core principle: "Frontend
 * validation improves usability; server-side validation enforces
 * correctness."). Every function here throws/returns the same shape a
 * caller can drop straight into a zod `.refine()` or `superRefine()`. */

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase()
}

/** Only the organisation's configured company domain is allowed -- but
 * the domain is configuration (Organisation.email_domain), not
 * hard-coded, so it's a parameter. `allowedDomain` of null/undefined
 * means the organisation has no domain restriction. */
export function validateCompanyEmailDomain(email: string, allowedDomain: string | null | undefined): string {
  const normalized = normalizeEmail(email)
  if (!allowedDomain) return normalized
  const domain = normalized.split('@').pop() ?? ''
  if (domain !== allowedDomain.trim().toLowerCase()) {
    throw new Error(`Email must use the '${allowedDomain}' company domain.`)
  }
  return normalized
}

/** The one `from <= to` comparison mechanism (docs/modules/common_validation.md
 * #2) -- equal values are valid (same-day validity), only start > end is
 * rejected. Accepts ISO date/datetime strings, as produced by
 * `<input type="date">`/`<input type="datetime-local">`
 * (components/forms/DateField.tsx), or Date objects. Whether past/future
 * dates are allowed at all is left to the calling module. */
export function validateDateRange(
  start: string | Date,
  end: string | Date,
  { startLabel = 'Start date', endLabel = 'End date' }: { startLabel?: string; endLabel?: string } = {},
): void {
  const startTime = start instanceof Date ? start.getTime() : new Date(start).getTime()
  const endTime = end instanceof Date ? end.getTime() : new Date(end).getTime()
  if (startTime > endTime) {
    throw new Error(`${startLabel} must not be after ${endLabel}.`)
  }
}

export interface IdFormat {
  pattern: RegExp
  example: string
}

/** One prefix+digit-count shape per entity, shared with backend's
 * app/core/id_formats.py -- Quotation (QXXXXXX), Order (OXXXXXX), User
 * (XXXXX), Product (PRXXXX), Material (MXXXX). */
export const ID_FORMATS = {
  quotation: { pattern: /^Q\d{6}$/, example: 'QXXXXXX' },
  order: { pattern: /^O\d{6}$/, example: 'OXXXXXX' },
  user: { pattern: /^\d{5}$/, example: 'XXXXX' },
  product: { pattern: /^PR\d{4}$/, example: 'PRXXXX' },
  material: { pattern: /^M\d{4}$/, example: 'MXXXX' },
} as const satisfies Record<string, IdFormat>

export type IdFormatName = keyof typeof ID_FORMATS

export function validateIdFormat(name: IdFormatName, value: string): string {
  const format = ID_FORMATS[name]
  if (!format.pattern.test(value)) {
    throw new Error(`must match the format ${format.example}`)
  }
  return value
}
