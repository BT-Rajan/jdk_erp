import { describe, expect, it } from 'vitest'
import { currencyDecimals, DEFAULT_CURRENCY } from './currency'

describe('currency', () => {
  it('defaults to KWD', () => {
    expect(DEFAULT_CURRENCY).toBe('KWD')
  })

  it('gives KWD three decimal places', () => {
    expect(currencyDecimals('KWD')).toBe(3)
  })

  it('gives USD two decimal places', () => {
    expect(currencyDecimals('USD')).toBe(2)
  })

  it('defaults an unknown currency to two decimal places', () => {
    expect(currencyDecimals('XYZ')).toBe(2)
  })

  it('is case-insensitive', () => {
    expect(currencyDecimals('kwd')).toBe(3)
  })
})
