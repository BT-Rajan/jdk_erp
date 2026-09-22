import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
import { useAuth } from '@/lib/auth/AuthContext'

/** The first route behind RequireAuth -- a placeholder until Phase 2
 * (docs/ROADMAP.md, master data) gives it something to show. */
export function DashboardPage() {
  const { user } = useAuth()

  return (
    <div className="space-y-6">
      <PageHeader title={`Welcome, ${user?.full_name ?? ''}`} subtitle="This is the foundation shell -- business modules land here as they're built." />
      <EmptyState
        title="Nothing to show yet"
        message="See /styleguide for a live reference of every available component."
      />
    </div>
  )
}
