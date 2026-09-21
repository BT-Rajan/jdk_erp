import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface FilterBarProps {
  children: ReactNode
  className?: string
}

/** The standard grid every list page's search/filter row uses, instead
 * of each page inlining its own one-off `gridTemplateColumns`. */
export function FilterBar({ children, className }: FilterBarProps) {
  return <div className={cn('grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-4', className)}>{children}</div>
}
