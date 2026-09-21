import { formatNumber } from '@/lib/format'

export interface NumberDisplayProps {
  value: number | string | null | undefined
  options?: Intl.NumberFormatOptions
  className?: string
}

export function NumberDisplay({ value, options, className }: NumberDisplayProps) {
  return <span className={className}>{formatNumber(value, options)}</span>
}
