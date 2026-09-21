import type { ReactNode } from 'react'

export interface KeyValueProps {
  label: string
  value?: ReactNode
  children?: ReactNode
}

/** The "key-value/detail view" primitive -- a labeled value, falling
 * back to an em-dash for anything empty (the same empty-value
 * convention formatCurrency/formatDate/formatPercent use). */
export function KeyValue({ label, value, children }: KeyValueProps) {
  const content = children ?? value
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-gold-100/50">{label}</dt>
      <dd className="mt-0.5 text-sm text-gold-100">{content ?? '—'}</dd>
    </div>
  )
}
