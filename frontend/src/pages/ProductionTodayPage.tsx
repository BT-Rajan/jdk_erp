import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import { PRODUCTION_ORDER_STATUS_LABELS, PRODUCTION_ORDER_STATUS_TONES } from './productionShared'

/** Mirrors backend/app/api/production_status.py. */
export interface DayOrder {
  production_order_id: number
  order_number: string
  sequence: number | null
  product_id: number
  product_name: string | null
  unit_of_measure_id: number
  planned_quantity: string
  produced_quantity: string
  remaining_quantity: string
  status: string
  scheduled_date: string
  required_by_date: string | null
  production_line_name: string | null
  source_type: string
  sales_order_number: string | null
  sales_order_line_number: number | null
  exceptions: string[]
}

export interface DayStatus {
  date: string
  is_working_day: boolean
  previous_working_day: string
  next_working_day: string
  order_count: number
  completed_count: number
  in_progress_count: number
  not_started_count: number
  cancelled_count: number
  totals: { unit_of_measure_id: number; scheduled_quantity: string; produced_quantity: string; remaining_quantity: string }[]
  orders: DayOrder[]
}

const EXCEPTION_LABELS: Record<string, string> = {
  late: 'Scheduled after required-by',
  overdue: 'Required-by passed',
  not_produced: 'Scheduled day passed, not produced',
  material_shortage: 'Material short',
  schedule_overload: 'Day overloaded',
  cancelled: 'Cancelled',
}
const EXECUTABLE = ['issued', 'in_progress', 'partially_completed']
const qty = (value: string) => formatNumber(value, { maximumFractionDigits: 4 })

/** Production -> Today (P7): what should be produced on a day and where it
 * stands. Everything comes from Production Orders and their executions;
 * Record Production opens P6's action on the order. */
export function ProductionTodayPage() {
  const navigate = useNavigate()
  const [day, setDay] = useState<string | null>(null)
  const [status, setStatus] = useState<DayStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [units, setUnits] = useState<LookupOption[]>([])

  useEffect(() => {
    setLoading(true)
    apiClient
      .get<DayStatus>('/api/production-status/day', { params: day ? { date: day } : {} })
      .then((res) => {
        setStatus(res.data)
        setError(null)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true)
        else setError(err instanceof ApiError ? err.message : 'Failed to load the production day.')
      })
      .finally(() => setLoading(false))
  }, [day])

  useEffect(() => {
    apiClient
      .get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } })
      .then((res) => setUnits(res.data.data))
      .catch(() => undefined)
  }, [])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u.code ?? ''])), [units])
  const unit = (id: number) => unitsById.get(id) ?? ''

  if (denied) return <AccessDeniedState message="Daily production needs the production view or execute permission." />

  const columns: DataTableColumn<DayOrder>[] = [
    { key: 'sequence', label: '#', render: (r) => r.sequence ?? '—' },
    { key: 'order', label: 'Order', alwaysVisible: true, render: (r) => r.order_number },
    { key: 'product', label: 'Product', render: (r) => r.product_name ?? `Product ${r.product_id}` },
    { key: 'planned', label: 'Planned', align: 'right', render: (r) => `${qty(r.planned_quantity)} ${unit(r.unit_of_measure_id)}` },
    { key: 'produced', label: 'Produced', align: 'right', render: (r) => `${qty(r.produced_quantity)} ${unit(r.unit_of_measure_id)}` },
    { key: 'remaining', label: 'Remaining', align: 'right', render: (r) => `${qty(r.remaining_quantity)} ${unit(r.unit_of_measure_id)}` },
    {
      key: 'status',
      label: 'Status',
      alwaysVisible: true,
      render: (r) => (
        <Badge tone={PRODUCTION_ORDER_STATUS_TONES[r.status] ?? 'neutral'}>{PRODUCTION_ORDER_STATUS_LABELS[r.status] ?? r.status}</Badge>
      ),
    },
    { key: 'required_by', label: 'Required By', hideBelow: 'md', render: (r) => formatDate(r.required_by_date) },
    {
      key: 'source',
      label: 'Source',
      hideBelow: 'lg',
      render: (r) =>
        r.source_type === 'independent' ? 'Independent' : `${r.sales_order_number ?? '—'}${r.sales_order_line_number ? ` / line ${r.sales_order_line_number}` : ''}`,
    },
    {
      key: 'exceptions',
      label: 'Exceptions',
      render: (r) => (
        <span className="flex flex-wrap gap-1">
          {r.exceptions.map((e) => (
            <Badge key={e} tone={e === 'cancelled' ? 'neutral' : 'danger'}>
              {EXCEPTION_LABELS[e] ?? e}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      key: 'actions',
      label: '',
      align: 'right',
      alwaysVisible: true,
      render: (r) => (
        <span className="flex justify-end gap-2">
          {EXECUTABLE.includes(r.status) && (
            <Button onClick={() => navigate(`/production/orders/${r.production_order_id}?record=1`)}>Record Production</Button>
          )}
          <Button variant="secondary" onClick={() => navigate(`/production/orders/${r.production_order_id}`)}>
            Open
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Production Today" subtitle="What should be produced on this day, and where it stands." />
      <Alert variant="danger">{error}</Alert>
      <Card className="flex flex-wrap items-end gap-3 p-4 sm:p-6">
        <Button variant="secondary" onClick={() => status && setDay(status.previous_working_day)} disabled={!status}>
          Previous working day
        </Button>
        <DateField label="Production date" value={status?.date ?? ''} onChange={(e) => e.target.value && setDay(e.target.value)} />
        <Button variant="secondary" onClick={() => status && setDay(status.next_working_day)} disabled={!status}>
          Next working day
        </Button>
        <Button variant="secondary" onClick={() => setDay(null)}>
          Today
        </Button>
      </Card>
      {!status ? (
        <Spinner />
      ) : (
        <>
          {!status.is_working_day && <Alert variant="info">{formatDate(status.date)} is not a working day.</Alert>}
          <Card className="grid grid-cols-2 gap-4 p-4 text-sm sm:grid-cols-4 lg:grid-cols-7 sm:p-6">
            {status.totals.map((t) => (
              <div key={t.unit_of_measure_id} className="col-span-2 sm:col-span-4 lg:col-span-3 flex flex-wrap gap-4">
                <span><span className="text-gold-100/50">Scheduled </span>{`${qty(t.scheduled_quantity)} ${unit(t.unit_of_measure_id)}`}</span>
                <span><span className="text-gold-100/50">Produced </span>{`${qty(t.produced_quantity)} ${unit(t.unit_of_measure_id)}`}</span>
                <span><span className="text-gold-100/50">Remaining </span>{`${qty(t.remaining_quantity)} ${unit(t.unit_of_measure_id)}`}</span>
              </div>
            ))}
            <span><span className="text-gold-100/50">Orders </span>{status.order_count}</span>
            <span><span className="text-gold-100/50">Completed </span>{status.completed_count}</span>
            <span><span className="text-gold-100/50">In progress </span>{status.in_progress_count}</span>
            <span><span className="text-gold-100/50">Not started </span>{status.not_started_count}</span>
            {status.cancelled_count > 0 && <span><span className="text-gold-100/50">Cancelled </span>{status.cancelled_count}</span>}
          </Card>
          <Card className="p-4 sm:p-6">
            <DataTable
              columns={columns}
              rows={status.orders}
              rowKey={(r) => r.production_order_id}
              loading={loading}
              emptyTitle="Nothing scheduled"
              emptyMessage="Issued Production Orders scheduled on this day appear here."
            />
          </Card>
        </>
      )}
    </div>
  )
}
