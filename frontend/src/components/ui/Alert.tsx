import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import { cn } from '@/lib/cn'

export type AlertVariant = 'success' | 'warning' | 'danger' | 'info'

export interface AlertProps {
  variant?: AlertVariant
  children: ReactNode
  className?: string
}

const VARIANT_CLASSES: Record<AlertVariant, string> = {
  success: 'border-success-500/40 bg-success-500/10 text-success-500',
  warning: 'border-warning-500/40 bg-warning-500/10 text-warning-500',
  danger: 'border-danger-500/40 bg-danger-500/10 text-danger-500',
  info: 'border-info-500/40 bg-info-500/10 text-info-500',
}

const VARIANT_ICONS: Record<AlertVariant, typeof Info> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
}

/** Renders nothing when `children` is falsy, so callers can write
 * `<Alert variant="danger">{error}</Alert>` unconditionally instead of
 * `{error && <Alert>...}` at every call site. */
export function Alert({ variant = 'info', children, className }: AlertProps) {
  if (!children) return null
  const Icon = VARIANT_ICONS[variant]

  return (
    <div
      role="alert"
      className={cn('flex items-start gap-2 rounded-md border px-3 py-2 text-sm', VARIANT_CLASSES[variant], className)}
    >
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span className="text-gold-100">{children}</span>
    </div>
  )
}
