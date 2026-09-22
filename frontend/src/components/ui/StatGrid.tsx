import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface StatGridProps {
  children: ReactNode
  className?: string
}

/** The responsive grid every row of StatCards sits in -- the same
 * collapse-to-fewer-columns pattern as FilterBar, so a dashboard's stat
 * row doesn't need its own one-off grid classes (a real gap: the
 * original kitchen-sink demo hand-rolled a fixed 3-column grid that
 * never collapsed on narrow screens). */
export function StatGrid({ children, className }: StatGridProps) {
  return <div className={cn('grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}>{children}</div>
}
