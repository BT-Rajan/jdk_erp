import { formatPercent } from '@/lib/format'

export interface PercentageProps {
  value: number | string | null | undefined
  decimals?: number
  className?: string
}

export function Percentage({ value, decimals, className }: PercentageProps) {
  return <span className={className}>{formatPercent(value, decimals)}</span>
}
