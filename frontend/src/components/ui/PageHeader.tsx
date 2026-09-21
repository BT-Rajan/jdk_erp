import type { ReactNode } from 'react'

export interface PageHeaderProps {
  title: string
  subtitle?: string
  actions?: ReactNode
}

/** Every list/detail page composes this -- never re-declares the header
 * markup inline (jdk_clean built this once but most list pages
 * duplicated it anyway; that mistake isn't repeated here). */
export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="font-display text-3xl font-medium text-gold-100">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-gold-100/50">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
