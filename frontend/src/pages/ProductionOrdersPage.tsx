import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { KeyValue } from '@/components/ui/KeyValue'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatDateTime, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import { PRODUCTION_ORDER_STATUS_LABELS as STATUS_LABELS, PRODUCTION_ORDER_STATUS_TONES as STATUS_TONES } from './productionShared'

/** Mirrors backend/app/api/production_orders.py's ProductionOrderOut. */
export interface ProductionOrder {
  id: number
  order_number: string
  status: 'draft' | 'issued' | 'in_progress' | 'partially_completed' | 'completed' | 'cancelled'
  product_id: number
  product_name: string | null
  unit_of_measure_id: number
  quantity: string
  machine_name: string | null
  production_line_name: string | null
  scheduled_date: string
  notes: string | null
  bom_id: number | null
  bom_base_quantity: string | null
  components: {
    raw_material_id: number
    raw_material_name: string
    quantity: string
    unit_of_measure_id: number
    required_quantity: string
    consumed_quantity?: string
    available_quantity?: string | null
  }[]
  produced_quantity?: string
  remaining_quantity?: string
  started_at?: string | null
  executions?: {
    id: number
    sequence: number
    produced_quantity: string
    unit_of_measure_id: number
    executed_at: string
    notes: string | null
    status: string
  }[]
  production_plan_id: number
  plan_source_type: 'customer_demand' | 'independent'
  production_schedule_entry_id: number
  production_requirement_id: number | null
  sales_order_number: string | null
  sales_order_line_number: number | null
  required_by_date: string | null
  created_at: string
  issued_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  history: { action: string; actor_user_id: number | null; created_at: string; details: string | null }[]
}

const EXECUTABLE = ['issued', 'in_progress', 'partially_completed']
const HISTORY_LABELS: Record<string, string> = {
  production_order_created: 'Created',
  production_order_updated: 'Edited',
  production_order_issued: 'Issued',
  production_order_cancelled: 'Cancelled',
  production_started: 'Production started',
  production_recorded: 'Production recorded',
}

const qty = (value: string | null) => (value === null ? '—' : formatNumber(value, { maximumFractionDigits: 4 }))
const source = (o: ProductionOrder) =>
  o.plan_source_type === 'independent' ? 'Independent' : `${o.sales_order_number ?? '—'}${o.sales_order_line_number ? ` / line ${o.sales_order_line_number}` : ''}`

function useUnitCodes() {
  const [units, setUnits] = useState<LookupOption[]>([])
  useEffect(() => {
    apiClient
      .get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } })
      .then((res) => setUnits(res.data.data))
      .catch(() => undefined)
  }, [])
  const byId = useMemo(() => new Map(units.map((u) => [u.id, u.code ?? ''])), [units])
  return (id: number) => byId.get(id) ?? ''
}

/** Production -> Orders (P5): production work formally issued to the
 * factory. Orders are created from schedule entries (Production ->
 * Schedule / Planning). Nothing here moves stock. */
export function ProductionOrdersPage() {
  const navigate = useNavigate()
  const [orders, setOrders] = useState<ProductionOrder[]>([])
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(true)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const unit = useUnitCodes()

  useEffect(() => {
    setLoading(true)
    apiClient
      .get<ProductionOrder[]>('/api/production-orders', {
        params: { status: status || undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined },
      })
      .then((res) => {
        setOrders(res.data)
        setError(null)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true)
        else setError(err instanceof ApiError ? err.message : 'Failed to load production orders.')
      })
      .finally(() => setLoading(false))
  }, [status, dateFrom, dateTo])

  if (denied) return <AccessDeniedState message="Production orders need the production view permission." />

  const columns: DataTableColumn<ProductionOrder>[] = [
    { key: 'number', label: 'Order', alwaysVisible: true, render: (o) => o.order_number },
    { key: 'product', label: 'Product', render: (o) => o.product_name ?? `Product ${o.product_id}` },
    { key: 'quantity', label: 'Quantity', align: 'right', render: (o) => `${qty(o.quantity)} ${unit(o.unit_of_measure_id)}` },
    { key: 'date', label: 'Scheduled', render: (o) => formatDate(o.scheduled_date) },
    { key: 'line', label: 'Production Line', hideBelow: 'md', render: (o) => o.production_line_name ?? '—' },
    { key: 'source', label: 'Source', hideBelow: 'sm', render: source },
    { key: 'required_by', label: 'Required By', hideBelow: 'md', render: (o) => formatDate(o.required_by_date) },
    { key: 'status', label: 'Status', render: (o) => <Badge tone={STATUS_TONES[o.status] ?? 'neutral'}>{STATUS_LABELS[o.status] ?? o.status}</Badge> },
    {
      key: 'open',
      label: '',
      align: 'right',
      alwaysVisible: true,
      render: (o) => (
        <Button variant="secondary" onClick={() => navigate(`/production/orders/${o.id}`)}>
          Open
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Production Orders" subtitle="Production work formally issued to the factory. Create orders from the production schedule." />
      <Alert variant="danger">{error}</Alert>
      <Card className="space-y-3 p-4 sm:p-6">
        <FilterBar>
          <SelectField label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectField>
          <DateField label="Scheduled from" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <DateField label="Scheduled to" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </FilterBar>
        <DataTable columns={columns} rows={orders} rowKey={(o) => o.id} loading={loading} emptyTitle="No production orders" emptyMessage="Create one from a schedule entry." />
      </Card>
    </div>
  )
}

type Dialog = 'edit' | 'cancel' | 'record' | null

function newReference(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
}

/** One Production Order (`/production/orders/:orderId`). */
export function ProductionOrderDetailPage() {
  const { orderId } = useParams()
  const navigate = useNavigate()
  const [order, setOrder] = useState<ProductionOrder | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [denied, setDenied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [quantity, setQuantity] = useState('')
  const [notes, setNotes] = useState('')
  const [reason, setReason] = useState('')
  const [executedAt, setExecutedAt] = useState('')
  // One reference per Record Production submission: a retry never posts twice.
  const [reference, setReference] = useState('')
  const unit = useUnitCodes()

  const load = useCallback(() => {
    apiClient
      .get<ProductionOrder>(`/api/production-orders/${orderId}`)
      .then((res) => setOrder(res.data))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true)
        else setLoadError(err instanceof ApiError ? err.message : 'Failed to load the production order.')
      })
  }, [orderId])

  useEffect(() => {
    load()
  }, [load])

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      setDialog(null)
      load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (denied) return <AccessDeniedState message="Production orders need the production view permission." />
  if (loadError) return <Alert variant="danger">{loadError}</Alert>
  if (!order) return <Spinner />

  const u = unit(order.unit_of_measure_id)
  return (
    <div className="space-y-6">
      <PageHeader
        title={`Production Order ${order.order_number}`}
        subtitle={order.product_name ?? undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate('/production/orders')}>All Orders</Button>
            {order.status === 'draft' && (
              <>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setQuantity(String(Number(order.quantity)))
                    setNotes(order.notes ?? '')
                    setDialog('edit')
                  }}
                >
                  Edit
                </Button>
                <Button onClick={() => act(() => apiClient.post(`/api/production-orders/${order.id}/issue`))} isLoading={busy && dialog === null} disabled={busy}>
                  Issue
                </Button>
              </>
            )}
            {order.status === 'issued' && (
              <Button variant="secondary" onClick={() => act(() => apiClient.post(`/api/production-orders/${order.id}/start`))} disabled={busy}>
                Start
              </Button>
            )}
            {EXECUTABLE.includes(order.status) && (
              <Button
                onClick={() => {
                  setQuantity('')
                  setNotes('')
                  setExecutedAt('')
                  setReference(newReference())
                  setDialog('record')
                }}
              >
                Record Production
              </Button>
            )}
            {['draft', 'issued', 'in_progress'].includes(order.status) && Number(order.produced_quantity ?? 0) === 0 && (
              <Button
                variant="danger"
                onClick={() => {
                  setReason('')
                  setDialog('cancel')
                }}
              >
                Cancel Order
              </Button>
            )}
          </div>
        }
      />
      {!dialog && <Alert variant="danger">{actionError}</Alert>}
      {order.status === 'cancelled' && order.cancellation_reason && <Alert variant="danger">Cancelled: {order.cancellation_reason}</Alert>}

      <Card className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <KeyValue label="Status">
          <Badge tone={STATUS_TONES[order.status] ?? 'neutral'}>{STATUS_LABELS[order.status] ?? order.status}</Badge>
        </KeyValue>
        <KeyValue label="Planned Quantity" value={`${qty(order.quantity)} ${u}`} />
        <KeyValue label="Produced" value={`${qty(order.produced_quantity ?? '0')} ${u}`} />
        <KeyValue label="Remaining" value={`${qty(order.remaining_quantity ?? order.quantity)} ${u}`} />
        <KeyValue label="Scheduled Date" value={formatDate(order.scheduled_date)} />
        <KeyValue label="Production Line" value={`${order.production_line_name ?? '—'} (${order.machine_name ?? '—'})`} />
        <KeyValue label="Source" value={source(order)} />
        <KeyValue label="Required By" value={formatDate(order.required_by_date)} />
        <KeyValue label="Production Plan" value={`#${order.production_plan_id}`} />
        <KeyValue label="Schedule Entry" value={`#${order.production_schedule_entry_id}`} />
        <KeyValue label="Issued" value={order.issued_at ? formatDateTime(order.issued_at) : '—'} />
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>BOM basis and raw-material requirements</FormSectionHeading>
        {order.components.length === 0 ? (
          <p className="text-sm text-gold-100/60">Snapshotted from the plan's BOM basis when the order is issued.</p>
        ) : (
          <>
            <p className="text-sm text-gold-100/60">
              BOM #{order.bom_id}, per {qty(order.bom_base_quantity)} {u}. Fixed at issue; later BOM changes do not affect this order.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                    <th className="py-2 pr-3">Raw material</th>
                    <th className="py-2 pr-3 text-right">Per BOM base</th>
                    <th className="py-2 pr-3 text-right">Required for this order</th>
                    <th className="py-2 pr-3 text-right">Consumed</th>
                    <th className="py-2 text-right">Available now</th>
                  </tr>
                </thead>
                <tbody>
                  {order.components.map((c) => (
                    <tr key={c.raw_material_id} className="border-t border-ink-700">
                      <td className="py-2 pr-3">{c.raw_material_name}</td>
                      <td className="py-2 pr-3 text-right">{`${qty(c.quantity)} ${unit(c.unit_of_measure_id)}`}</td>
                      <td className="py-2 pr-3 text-right">{`${qty(c.required_quantity)} ${unit(c.unit_of_measure_id)}`}</td>
                      <td className="py-2 pr-3 text-right">{`${qty(c.consumed_quantity ?? '0')} ${unit(c.unit_of_measure_id)}`}</td>
                      <td className="py-2 text-right">{c.available_quantity == null ? '—' : `${qty(c.available_quantity)} ${unit(c.unit_of_measure_id)}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Execution history</FormSectionHeading>
        {(order.executions ?? []).length === 0 ? (
          <p className="text-sm text-gold-100/60">No production recorded yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                <th className="py-2 pr-3">Execution</th>
                <th className="py-2 pr-3">Date</th>
                <th className="py-2 pr-3 text-right">Produced</th>
                <th className="py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {(order.executions ?? []).map((e) => (
                <tr key={e.id} className="border-t border-ink-700">
                  <td className="py-2 pr-3">{e.sequence}</td>
                  <td className="py-2 pr-3">{formatDateTime(e.executed_at)}</td>
                  <td className="py-2 pr-3 text-right">{`${qty(e.produced_quantity)} ${unit(e.unit_of_measure_id)}`}</td>
                  <td className="py-2">{e.status === 'posted' ? 'Posted' : e.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>History</FormSectionHeading>
        <ul className="divide-y divide-ink-700 text-sm">
          {order.history.map((h, i) => (
            <li key={i} className="py-2">
              <span className="font-medium">{HISTORY_LABELS[h.action] ?? h.action}</span>
              <span className="text-gold-100/50"> · {formatDateTime(h.created_at)}</span>
              {h.details && <div className="text-xs text-gold-100/60">{h.details}</div>}
            </li>
          ))}
        </ul>
      </Card>

      <Modal
        open={dialog !== null}
        title={dialog === 'cancel' ? 'Cancel production order' : dialog === 'record' ? 'Record production' : 'Edit draft'}
        onClose={() => setDialog(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDialog(null)} disabled={busy}>Back</Button>
            <Button
              variant={dialog === 'cancel' ? 'danger' : 'primary'}
              isLoading={busy}
              disabled={busy || (dialog === 'cancel' ? !reason.trim() : !quantity.trim())}
              onClick={() =>
                dialog === 'cancel'
                  ? act(() => apiClient.post(`/api/production-orders/${order.id}/cancel`, { reason }))
                  : dialog === 'record'
                    ? act(() =>
                        apiClient.post(`/api/production-orders/${order.id}/executions`, {
                          produced_quantity: quantity.trim(),
                          executed_at: executedAt ? new Date(executedAt).toISOString() : null,
                          notes: notes.trim() || null,
                          client_reference: reference,
                        }),
                      )
                    : act(() => apiClient.patch(`/api/production-orders/${order.id}`, { quantity: quantity.trim(), notes: notes.trim() || null }))
              }
            >
              {dialog === 'cancel' ? 'Cancel Order' : dialog === 'record' ? 'Post Production' : 'Save'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert variant="danger">{actionError}</Alert>
          {dialog === 'edit' && (
            <>
              <TextField label="Production quantity" type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
              <TextareaField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </>
          )}
          {dialog === 'cancel' && <TextareaField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />}
          {dialog === 'record' && (
            <>
              <p className="text-sm text-gold-100/70">
                Remaining {qty(order.remaining_quantity ?? order.quantity)} {u}. Raw materials are consumed from this order's BOM snapshot
                and the output goes into Finished Goods stock -- not to a customer.
              </p>
              <TextField label="Quantity produced" required type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
              <TextField label="Produced at (optional)" type="datetime-local" value={executedAt} onChange={(e) => setExecutedAt(e.target.value)} />
              <TextareaField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </>
          )}
        </div>
      </Modal>
    </div>
  )
}
