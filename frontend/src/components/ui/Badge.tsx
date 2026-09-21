import { cn } from '@/lib/cn'

export type BadgeTone = 'neutral' | 'gold' | 'success' | 'warning' | 'danger' | 'info'

export interface BadgeProps {
  children: string
  tone?: BadgeTone
  className?: string
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-ink-600 text-gold-100/80',
  gold: 'bg-gold-400/15 text-gold-300',
  success: 'bg-success-500/15 text-success-500',
  warning: 'bg-warning-500/15 text-warning-500',
  danger: 'bg-danger-500/15 text-danger-500',
  info: 'bg-info-500/15 text-info-500',
}

export function Badge({ children, tone = 'neutral', className }: BadgeProps) {
  return (
    <span className={cn('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium', TONE_CLASSES[tone], className)}>
      {children}
    </span>
  )
}

export interface StatusBadgeProps {
  status: string
  /** A caller-supplied, domain-scoped status->tone map -- not one global
   * map shared by every module's status vocabulary (jdk_clean's single
   * 30+-entry STATUS_TONES map only avoided collisions because its
   * strings happened not to overlap, and it caused a confirmed
   * inconsistency between Alert and Badge over which colour meant
   * "info"). Falls back to 'neutral' for a status the caller didn't map. */
  toneMap?: Record<string, BadgeTone>
  className?: string
}

export function StatusBadge({ status, toneMap, className }: StatusBadgeProps) {
  return (
    <Badge tone={toneMap?.[status] ?? 'neutral'} className={className}>
      {status}
    </Badge>
  )
}
