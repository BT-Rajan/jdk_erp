import type { ReactElement, ReactNode } from 'react'
import { ResponsiveContainer } from 'recharts'
import { Alert } from '@/components/ui/Alert'
import { EmptyState } from '@/components/ui/EmptyState'
import { Spinner } from '@/components/ui/Spinner'

export interface ChartStateProps {
  loading?: boolean
  error?: string
  empty?: boolean
  emptyMessage?: string
  height: number
  children: ReactNode
}

/** The one place LineChart/BarChart/PieChart share loading/empty/error
 * handling and responsive sizing -- composes the existing
 * Spinner/EmptyState/Alert rather than each chart re-implementing these
 * three states. */
export function ChartState({ loading, error, empty, emptyMessage, height, children }: ChartStateProps) {
  if (loading) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <Spinner />
      </div>
    )
  }

  if (error) return <Alert variant="danger">{error}</Alert>

  if (empty) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <EmptyState title="No data" message={emptyMessage} />
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      {children as ReactElement}
    </ResponsiveContainer>
  )
}
