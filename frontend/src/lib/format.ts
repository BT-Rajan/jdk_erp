const EMPTY = '—'

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isNaN(n) ? null : n
}

export function formatCurrency(
  value: number | string | null | undefined,
  currency = 'USD',
  locale = 'en-US',
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(n)
}

export function formatNumber(
  value: number | string | null | undefined,
  options?: Intl.NumberFormatOptions,
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  return new Intl.NumberFormat('en-US', options).format(n)
}

export function formatPercent(
  value: number | string | null | undefined,
  decimals = 1,
): string {
  const n = toNumber(value)
  if (n === null) return EMPTY
  return `${n.toFixed(decimals)}%`
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/

/** Deliberately not Intl.DateTimeFormat/toLocaleDateString -- those are
 * browser-locale-dependent, so the same record would render differently
 * depending on the viewer's OS settings. One fixed, explicit format
 * everywhere instead: DD-MM-YYYY (docs/modules/common_validation.md #2).
 * A plain `YYYY-MM-DD` date is formatted from its parts, never through
 * `new Date()`, so no timezone can shift it by a day. */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return EMPTY
  if (typeof value === 'string') {
    const match = ISO_DATE_RE.exec(value)
    if (match) return `${match[3]}-${match[2]}-${match[1]}`
  }
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return EMPTY
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return EMPTY
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return EMPTY
  return `${formatDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
