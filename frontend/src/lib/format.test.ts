import { describe, expect, it } from 'vitest'
import { formatCurrency, formatDate, formatDateTime, formatNumber, formatPercent } from './format'

describe('formatCurrency', () => {
  it('formats a number in the given currency', () => {
    expect(formatCurrency(1234.5, 'USD')).toBe('$1,234.50')
  })

  it('returns the empty-value placeholder for null/undefined/empty/NaN', () => {
    expect(formatCurrency(null)).toBe('—')
    expect(formatCurrency(undefined)).toBe('—')
    expect(formatCurrency('')).toBe('—')
    expect(formatCurrency('not-a-number')).toBe('—')
  })

  it('accepts a numeric string', () => {
    expect(formatCurrency('50', 'USD')).toBe('$50.00')
  })
})

describe('formatNumber', () => {
  it('adds thousand separators', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
  })

  it('returns the empty-value placeholder for missing values', () => {
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
  })
})

describe('formatPercent', () => {
  it('formats with one decimal place by default', () => {
    expect(formatPercent(12.5)).toBe('12.5%')
  })

  it('respects a custom decimal count', () => {
    expect(formatPercent(12.3456, 2)).toBe('12.35%')
  })

  it('returns the empty-value placeholder for missing values', () => {
    expect(formatPercent(null)).toBe('—')
  })
})

describe('formatDate', () => {
  it('renders DD/MM/YYYY regardless of environment locale', () => {
    expect(formatDate(new Date(2026, 0, 5))).toBe('05/01/2026')
  })

  it('returns the empty-value placeholder for missing or invalid values', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDate('not-a-date')).toBe('—')
  })
})

describe('formatDateTime', () => {
  it('renders DD/MM/YYYY HH:MM in 24-hour time', () => {
    expect(formatDateTime(new Date(2026, 0, 5, 17, 6))).toBe('05/01/2026 17:06')
  })

  it('returns the empty-value placeholder for missing values', () => {
    expect(formatDateTime(null)).toBe('—')
  })
})
