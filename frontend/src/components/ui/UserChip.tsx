import { cn } from '@/lib/cn'
import { Avatar } from './Avatar'

export interface UserChipProps {
  src?: string | null
  name: string
  subtitle?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

/** Avatar + name + optional role/subtitle in one piece -- every call
 * site in jdk_clean hand-composed this itself since no such component
 * existed. */
export function UserChip({ src, name, subtitle, size = 'md', className }: UserChipProps) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <Avatar src={src} name={name} size={size} />
      <div>
        <p className="text-sm font-medium text-gold-100">{name}</p>
        {subtitle && <p className="text-xs text-gold-100/50">{subtitle}</p>}
      </div>
    </div>
  )
}
