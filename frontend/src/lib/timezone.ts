/** The one JDK/Kuwait timezone conversion path for the frontend --
 * mirrors backend/app/core/timezone.py. No component implements its own
 * timezone conversion (docs/modules/common_validation.md #3). */
export const JDK_TIMEZONE = 'Asia/Kuwait'

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** Converts a UTC ISO timestamp (as returned by every API in this
 * project) to its JDK/Kuwait local-time parts, formatted
 * DD/MM/YYYY HH:mm -- the one display format
 * (docs/modules/common_validation.md #3), independent of the viewer's
 * own OS/browser timezone. */
export function formatKuwaitTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return '—'

  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: JDK_TIMEZONE,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(d)

  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? ''
  return `${get('day')}/${get('month')}/${get('year')} ${pad(Number(get('hour')) % 24)}:${get('minute')}`
}
