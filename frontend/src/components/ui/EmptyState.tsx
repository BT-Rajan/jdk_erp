import type { ReactNode } from 'react'

export interface EmptyStateProps {
  title: string
  message?: string
  action?: ReactNode
}

export function EmptyState({ title, message, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <p className="font-display text-lg text-gold-100">{title}</p>
      {message && <p className="max-w-sm text-sm text-gold-100/60">{message}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
