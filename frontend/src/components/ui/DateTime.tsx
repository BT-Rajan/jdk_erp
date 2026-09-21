import { formatDate, formatDateTime } from '@/lib/format'

export interface DateTimeProps {
  value: string | Date | null | undefined
  withTime?: boolean
  className?: string
}

export function DateTime({ value, withTime = false, className }: DateTimeProps) {
  return <span className={className}>{withTime ? formatDateTime(value) : formatDate(value)}</span>
}
