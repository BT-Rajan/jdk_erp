import type { ReactNode } from 'react'

export interface FormSectionHeadingProps {
  children: ReactNode
}

/** A repeating list of these needs no manual "is this the first one"
 * prop threading -- `first:` handles it. */
export function FormSectionHeading({ children }: FormSectionHeadingProps) {
  return (
    <h2 className="mt-6 border-t border-ink-700 pt-6 text-sm font-semibold uppercase tracking-wide text-gold-300 first:mt-0 first:border-0 first:pt-0">
      {children}
    </h2>
  )
}
