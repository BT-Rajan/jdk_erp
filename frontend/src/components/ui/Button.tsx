import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Spinner } from './Spinner'

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'gradient'
export type ButtonSize = 'md' | 'sm'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  isLoading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'bg-gold-400 text-ink-950 hover:bg-gold-500 active:bg-gold-600',
  secondary: 'bg-ink-800 text-gold-100 border border-ink-600 hover:bg-ink-700',
  danger: 'bg-danger-500 text-white hover:bg-danger-500/90',
  ghost: 'bg-transparent text-gold-100 hover:bg-ink-800',
  // Reserved for hero moments (the auth screens' primary CTA today) --
  // everyday actions keep the flat `primary` look so the app's ordinary
  // buttons stay consistent per docs/DESIGN_SYSTEM.md.
  gradient:
    'bg-gradient-to-b from-gold-300 to-gold-600 text-ink-950 shadow-glow-gold hover:from-gold-200 hover:to-gold-500',
}

const SIZE_CLASSES: Record<ButtonSize, string> = {
  md: 'h-10 px-4 text-sm',
  sm: 'h-8 px-3 text-sm',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    isLoading = false,
    leftIcon,
    rightIcon,
    disabled,
    className,
    children,
    type = 'button',
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      className={cn(
        'relative inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400',
        'disabled:cursor-not-allowed disabled:opacity-50',
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...props}
    >
      {isLoading && (
        <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center">
          <Spinner size={16} />
        </span>
      )}
      {/* opacity-0, not visibility:hidden/display:none -- the label must
          stay in the accessibility tree (it's still the button's name)
          while disappearing visually so the spinner can take its place
          without changing the button's width. aria-busy communicates
          the loading state itself. */}
      <span className={cn('inline-flex items-center gap-2', isLoading && 'opacity-0')}>
        {leftIcon}
        {children}
        {rightIcon}
      </span>
    </button>
  )
})
