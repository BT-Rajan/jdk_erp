import { forwardRef, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Button, type ButtonProps } from './Button'

export interface IconButtonProps extends Omit<ButtonProps, 'leftIcon' | 'rightIcon' | 'children' | 'aria-label'> {
  icon: ReactNode
  /** Required, not optional: an icon-only button has no visible label,
   * so a screen-reader label is not something a caller can skip. */
  'aria-label': string
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, variant = 'ghost', size = 'md', className, ...props },
  ref,
) {
  return (
    <Button
      ref={ref}
      variant={variant}
      size={size}
      className={cn(size === 'sm' ? 'w-8 px-0' : 'w-10 px-0', className)}
      {...props}
    >
      {icon}
    </Button>
  )
})
