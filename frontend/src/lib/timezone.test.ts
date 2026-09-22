import { describe, expect, it } from 'vitest'
import { formatKuwaitTime, JDK_TIMEZONE } from './timezone'

describe('formatKuwaitTime', () => {
  it('is Asia/Kuwait', () => {
    expect(JDK_TIMEZONE).toBe('Asia/Kuwait')
  })

  it('converts a UTC timestamp to Kuwait local time (UTC+3), DD/MM/YYYY HH:mm', () => {
    expect(formatKuwaitTime('2026-09-22T09:00:00Z')).toBe('22/09/2026 12:00')
  })

  it('rolls over to the next day when the offset crosses midnight', () => {
    expect(formatKuwaitTime('2026-09-22T22:00:00Z')).toBe('23/09/2026 01:00')
  })

  it('returns the empty-value placeholder for missing or invalid values', () => {
    expect(formatKuwaitTime(null)).toBe('—')
    expect(formatKuwaitTime(undefined)).toBe('—')
    expect(formatKuwaitTime('not-a-date')).toBe('—')
  })
})
