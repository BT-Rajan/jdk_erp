import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spinner } from '@/components/ui/Spinner'
import { useAuth } from '@/lib/auth/AuthContext'

/** Gates every protected route -- client-side only, a usability
 * feature same as every other frontend check
 * (docs/ENGINEERING_PRINCIPLES.md #3, "UI visibility is only a
 * usability feature, not security"): the backend enforces the real
 * boundary on every request regardless of what this renders. Wraps a
 * layout route element (`<Route element={<RequireAuth><AppLayout/></RequireAuth>}>`),
 * not each leaf page individually. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-950">
        <Spinner size={32} />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}
