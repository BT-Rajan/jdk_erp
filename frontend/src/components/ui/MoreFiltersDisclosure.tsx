import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/cn'

export interface MoreFiltersDisclosureProps {
  children: ReactNode
  label?: string
}

/** Keeps advanced/less-used filters out of the way until asked for,
 * while the common ones in FilterBar stay immediately visible above
 * this. Collapsed by default. */
export function MoreFiltersDisclosure({ children, label = 'More filters' }: MoreFiltersDisclosureProps) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1 text-sm font-medium text-gold-300 transition-colors hover:text-gold-100"
      >
        {label}
        <ChevronDown size={14} aria-hidden="true" className={cn('transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  )
}
