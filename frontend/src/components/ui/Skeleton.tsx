import { cn } from '@/lib/cn'

export interface SkeletonProps {
  className?: string
}

/** A loading placeholder block -- size and shape via className (e.g.
 * `h-4 w-32`, `h-9 w-9 rounded-full`). Distinct from Spinner, which is
 * for an indeterminate whole-page/section wait; this is for a layout
 * that's about to be filled in (a table row, a card) so the page
 * doesn't jump once real content arrives. */
export function Skeleton({ className }: SkeletonProps) {
  return <div aria-hidden="true" className={cn('animate-pulse rounded-md bg-ink-700', className)} />
}
