import { Lock } from 'lucide-react'

export interface AccessDeniedStateProps {
  message?: string
}

/** Mirrors the backend's ACCESS_DENIED error contract
 * (backend/app/core/errors.py) -- the same situation on the frontend
 * gets the same name and a consistent full-section treatment, distinct
 * from EmptyState (which means "nothing here yet", not "you can't see
 * this"). */
export function AccessDeniedState({ message = "You don't have permission to view this." }: AccessDeniedStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <Lock size={32} aria-hidden="true" className="text-gold-100/40" />
      <p className="font-display text-lg text-gold-100">Access denied</p>
      <p className="max-w-sm text-sm text-gold-100/60">{message}</p>
    </div>
  )
}
