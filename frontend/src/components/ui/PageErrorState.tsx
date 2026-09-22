import { AlertOctagon } from 'lucide-react'
import { Button } from './Button'

export interface PageErrorStateProps {
  message?: string
  onRetry?: () => void
}

/** The default message mirrors the backend's generic SERVER_ERROR
 * fallback (backend/app/core/errors.py's `default_message`) -- a
 * full-page/section-level counterpart to the inline Alert, for when an
 * entire view failed to load rather than one action within it. */
export function PageErrorState({ message = 'Something went wrong. Please try again.', onRetry }: PageErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <AlertOctagon size={32} aria-hidden="true" className="text-danger-500" />
      <p className="font-display text-lg text-gold-100">Something went wrong</p>
      <p className="max-w-sm text-sm text-gold-100/60">{message}</p>
      {onRetry && <Button onClick={onRetry}>Try again</Button>}
    </div>
  )
}
