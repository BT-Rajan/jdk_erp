import { formatCurrency } from '@/lib/format'

export interface CurrencyProps {
  value: number | string | null | undefined
  currency?: string
  locale?: string
  className?: string
}

export function Currency({ value, currency = 'USD', locale = 'en-US', className }: CurrencyProps) {
  return <span className={className}>{formatCurrency(value, currency, locale)}</span>
}
