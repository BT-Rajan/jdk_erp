import { cn } from '@/lib/cn'

/** Shared base classes for every text-like input (text/number/date/
 * select/textarea) so the border, focus ring, and error state look
 * identical everywhere. */
export function inputClasses(hasError: boolean, className?: string) {
  return cn(
    'h-10 w-full rounded-md border bg-ink-800 px-3 text-sm text-gold-100 placeholder:text-gold-100/30',
    'focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400',
    'disabled:cursor-not-allowed disabled:opacity-50',
    hasError ? 'border-danger-500' : 'border-ink-600 focus:border-gold-400',
    className,
  )
}
