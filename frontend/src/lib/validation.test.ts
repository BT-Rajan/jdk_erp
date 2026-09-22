import { describe, expect, it } from 'vitest'
import {
  ID_FORMATS,
  normalizeEmail,
  validateCompanyEmailDomain,
  validateDateRange,
  validateIdFormat,
} from './validation'

describe('normalizeEmail', () => {
  it('lowercases and trims', () => {
    expect(normalizeEmail('  Ada@Example.COM  ')).toBe('ada@example.com')
  })
})

describe('validateCompanyEmailDomain', () => {
  it('accepts a matching domain', () => {
    expect(validateCompanyEmailDomain('ada@jdk.com', 'jdk.com')).toBe('ada@jdk.com')
  })

  it('is case-insensitive', () => {
    expect(validateCompanyEmailDomain('ada@JDK.COM', 'jdk.com')).toBe('ada@jdk.com')
  })

  it('rejects a different domain', () => {
    expect(() => validateCompanyEmailDomain('ada@gmail.com', 'jdk.com')).toThrow('jdk.com')
  })

  it('allows anything when no domain is configured', () => {
    expect(validateCompanyEmailDomain('ada@anywhere.com', null)).toBe('ada@anywhere.com')
  })
})

describe('validateDateRange', () => {
  it('accepts start before end', () => {
    expect(() => validateDateRange('2026-09-22', '2026-09-23')).not.toThrow()
  })

  it('accepts same-day as valid (From: 22/09/2026, Valid Till: 22/09/2026)', () => {
    expect(() => validateDateRange('2026-09-22', '2026-09-22')).not.toThrow()
  })

  it('rejects start after end (From: 23/09/2026, Valid Till: 22/09/2026)', () => {
    expect(() => validateDateRange('2026-09-23', '2026-09-22')).toThrow('must not be after')
  })

  it('uses the given field labels in the message', () => {
    expect(() =>
      validateDateRange('2026-09-23', '2026-09-22', { startLabel: 'Valid From', endLabel: 'Valid Till' }),
    ).toThrow('Valid From must not be after Valid Till')
  })
})

describe('ID_FORMATS', () => {
  it.each([
    ['quotation', 'Q000001', 'QQ00001'],
    ['order', 'O000042', 'O42'],
    ['user', '00001', '1'],
    ['product', 'PR0001', 'PRODUCT1'],
    ['material', 'M0001', 'MAT0001'],
  ] as const)('%s accepts %s and rejects %s', (name, valid, invalid) => {
    expect(validateIdFormat(name, valid)).toBe(valid)
    expect(() => validateIdFormat(name, invalid)).toThrow()
  })

  it('exposes the same five shapes as the backend', () => {
    expect(Object.keys(ID_FORMATS).sort()).toEqual(['material', 'order', 'product', 'quotation', 'user'])
  })
})
