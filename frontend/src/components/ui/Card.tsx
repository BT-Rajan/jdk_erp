import { forwardRef, type HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** A slightly more pronounced border/background -- for a card nested
   * inside another card, or one that needs to stand out (e.g. a summary
   * panel above a table). */
  strong?: boolean
}

/** The one "section/card" surface every module composes -- a thin
 * wrapper, no business logic, so it stays trivially portable. */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card({ strong = false, className, ...props }, ref) {
  return (
    <div
      ref={ref}
      className={cn(
        'rounded-lg border backdrop-blur-sm',
        strong ? 'border-gold-400/30 bg-ink-800/80' : 'border-ink-700 bg-ink-900/60',
        className,
      )}
      {...props}
    />
  )
})
