/** Mirrors backend/app/core/currency.py -- the one place both sides agree
 * on decimal precision per currency (docs/modules/common_validation.md #4).
 * KWD subdivides into 1000 fils (3 decimals), unlike most currencies' 2. */
export const DEFAULT_CURRENCY = 'KWD'

export const CURRENCY_DECIMALS: Record<string, number> = {
  KWD: 3,
  USD: 2,
  EUR: 2,
  GBP: 2,
}

export function currencyDecimals(currency: string = DEFAULT_CURRENCY): number {
  return CURRENCY_DECIMALS[currency.toUpperCase()] ?? 2
}
