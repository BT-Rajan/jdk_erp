import { cn } from '@/lib/cn'

export interface AvatarProps {
  /** An already-resolved image URL, or null/undefined for the initials
   * fallback. Fetching is the caller's responsibility -- jdk_clean's
   * Avatar fetched an authenticated blob internally regardless of whose
   * avatarUrl was passed in, which risked every <Avatar> on screen
   * resolving to the current logged-in user's own photo rather than the
   * person actually being displayed. */
  src?: string | null
  name: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_CLASSES = {
  sm: 'h-6 w-6 text-xs',
  md: 'h-9 w-9 text-sm',
  lg: 'h-12 w-12 text-base',
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return ''
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function Avatar({ src, name, size = 'md', className }: AvatarProps) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-ink-700 font-medium text-gold-200',
        SIZE_CLASSES[size],
        className,
      )}
    >
      {src ? <img src={src} alt={name} className="h-full w-full object-cover" /> : getInitials(name)}
    </span>
  )
}
