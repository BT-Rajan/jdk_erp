import type { ReactNode } from 'react'
import { Card } from './Card'

export interface StatCardProps {
  label: string
  value: ReactNode
  hint?: string
  icon?: ReactNode
}

/** No precedent existed in jdk_clean -- dashboards built stat tiles ad
 * hoc on GlassCard per page. One shared implementation instead. */
export function StatCard({ label, value, hint, icon }: StatCardProps) {
  return (
    <Card className="flex items-start justify-between gap-3 p-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-gold-100/50">{label}</p>
        <p className="mt-1 font-display text-2xl text-gold-100">{value}</p>
        {hint && <p className="mt-1 text-xs text-gold-100/50">{hint}</p>}
      </div>
      {icon && <div className="text-gold-400">{icon}</div>}
    </Card>
  )
}
