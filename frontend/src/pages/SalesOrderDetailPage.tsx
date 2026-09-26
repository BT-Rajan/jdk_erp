import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { KeyValue } from '@/components/ui/KeyValue'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { CheckboxField } from '@/components/forms/CheckboxField'
import { DateField } from '@/components/forms/DateField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { downloadFile } from '@/lib/downloadFile'
import { formatDate, formatDateTime, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import { HANDOFF_SOURCE_LABELS, ORDER_STATUS_LABELS, ORDER_STATUS_TONES, type SalesOrder } from './quotationShared'
import { DELIVERY_STATUS_LABELS, DELIVERY_STATUS_TONES, type DeliveryInstruction } from './deliveryShared'

interface LineEdit {
  product_id: number
  unit_of_measure_id: number
  quantity: string
  unit_price: string
}

function money(value: string, currency: string): string {
  return `${formatNumber(value, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} ${currency}`
}

/** One Sales Order (`/sales/orders/:orderId`), handed off to fulfilment
 * automatically on creation (S14.2). Cancel and Admin edit (date,
 * quantities, prices) are offered from the server's `can_cancel` /
 * `can_edit`; the server enforces both, re-prices any edit and records
 * every change with its reason. Delivered / remaining quantities and the
 * order's Delivery Instructions are read-only here (the instructions
 * only for users with the delivery permission). */
export function SalesOrderDetailPage() {
  const { orderId } = useParams()
  const navigate = useNavigate()
  const [order, setOrder] = useState<SalesOrder | null>(null)
  const [products, setProducts] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [editing, setEditing] = useState(false)
  const [editDate, setEditDate] = useState('')
  const [editLines, setEditLines] = useState<LineEdit[]>([])
  const [editReason, setEditReason] = useState('')
  // Production P1: changing an assessed line's quantity recomputes its
  // production demand -- the Admin confirms it; the server enforces it.
  const [confirmDemandChange, setConfirmDemandChange] = useState(false)
  // Line ids already assessed for fulfilment at hand-off (S15.2): changing
  // their quantity needs the confirmation below; null = not known.
  const [assessedLineIds, setAssessedLineIds] = useState<Set<number> | null>(null)
  // null = not visible to this user (no delivery permission).
  const [deliveries, setDeliveries] = useState<DeliveryInstruction[] | null>(null)

  const load = useCallback(async () => {
    const { data } = await apiClient.get<SalesOrder>(`/api/sales-orders/${orderId}`)
    setOrder(data)
    apiClient
      .get<{ sales_order_line_id: number }[]>(`/api/sales-orders/${orderId}/fulfilment`)
      .then((res) => setAssessedLineIds(new Set(res.data.map((row) => row.sales_order_line_id))))
      .catch(() => setAssessedLineIds(null))
    apiClient
      .get<PaginatedResponse<DeliveryInstruction>>('/api/delivery-instructions', { params: { sales_order_id: orderId, page_size: 100 } })
      .then((res) => setDeliveries(res.data.data))
      .catch(() => setDeliveries(null))
  }, [orderId])

  useEffect(() => {
    load().catch((err) => setLoadError(err instanceof ApiError ? err.message : 'Failed to load the sales order.'))
    Promise.all([
      apiClient.get<PaginatedResponse<LookupOption>>('/api/products', { params: { page_size: 200 } }),
      apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
    ])
      .then(([p, u]) => {
        setProducts(p.data.data)
        setUnits(u.data.data)
      })
      .catch(() => undefined)
  }, [load])

  const productsById = useMemo(() => new Map(products.map((p) => [p.id, p])), [products])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  function startEdit() {
    if (!order) return
    setEditDate(order.requested_delivery_date ?? '')
    setEditLines(
      order.lines.map((line) => ({
        product_id: line.product_id,
        unit_of_measure_id: line.unit_of_measure_id,
        quantity: String(Number(line.quantity)),
        unit_price: String(Number(line.unit_price)),
      })),
    )
    setEditReason('')
    setConfirmDemandChange(false)
    setEditing(true)
  }

  async function run(name: string, action: () => Promise<unknown>) {
    setBusy(name)
    setActionError(null)
    try {
      await action()
      setCancelling(false)
      setEditing(false)
      await load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(null)
    }
  }

  const assessedQuantityChanged =
    order !== null &&
    assessedLineIds !== null &&
    editLines.some((line, index) => {
      const original = order.lines[index]
      return original !== undefined && assessedLineIds.has(original.id) && Number(line.quantity) !== Number(original.quantity)
    })

  const cancel = () => run('cancel', () => apiClient.post(`/api/sales-orders/${orderId}/cancel`, { reason: cancelReason }))
  const saveEdit = () =>
    run('edit', () =>
      apiClient.patch(`/api/sales-orders/${orderId}`, {
        reason: editReason,
        requested_delivery_date: editDate || null,
        lines: editLines.map((line) => ({ ...line, quantity: line.quantity.trim(), unit_price: line.unit_price.trim() })),
        ...(assessedQuantityChanged ? { confirm_fulfilment_change: confirmDemandChange } : {}),
      }),
    )

  if (loadError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Sales Order" />
        <Alert variant="danger">{loadError}</Alert>
        <Button variant="secondary" onClick={() => navigate('/sales/orders')}>Back to Sales Orders</Button>
      </div>
    )
  }
  if (!order) return <Spinner />

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Sales Order ${order.order_number}`}
        subtitle={order.customer_name ?? undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate('/sales/orders')}>All Sales Orders</Button>
            {order.pdf_file && (
              <Button variant="secondary" onClick={() => downloadFile(order.pdf_file!).catch(() => setActionError('Failed to download the PDF.'))}>
                Order Confirmation PDF
              </Button>
            )}
            <Button variant="secondary" onClick={() => navigate(`/sales/quotations/${order.quotation_id}`)}>View Quotation</Button>
            {order.can_edit && !editing && <Button variant="secondary" onClick={startEdit}>Edit (Admin)</Button>}
            {order.can_cancel && !cancelling && (
              <Button variant="danger" onClick={() => setCancelling(true)}>Cancel Order</Button>
            )}
          </div>
        }
      />

      <Alert variant="danger">{actionError}</Alert>
      {order.status === 'cancelled' && order.cancellation_reason && (
        <Alert variant="danger">Cancelled: {order.cancellation_reason}</Alert>
      )}

      {cancelling && (
        <Card className="space-y-3 p-6">
          <FormSectionHeading>Cancel Sales Order</FormSectionHeading>
          <TextareaField label="Cancellation reason" required value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setCancelling(false)} disabled={busy !== null}>Keep Order</Button>
            <Button variant="danger" onClick={cancel} isLoading={busy === 'cancel'} disabled={busy !== null || !cancelReason.trim()}>
              Confirm Cancellation
            </Button>
          </div>
        </Card>
      )}

      <Card className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <KeyValue label="Status">
          <Badge tone={ORDER_STATUS_TONES[order.status] ?? 'neutral'}>{ORDER_STATUS_LABELS[order.status] ?? order.status}</Badge>
        </KeyValue>
        <KeyValue label="Customer" value={order.customer_name ?? '—'} />
        <KeyValue label="Quotation" value={order.quotation_number ?? '—'} />
        <KeyValue label="Order Date" value={formatDate(order.order_date)} />
        <KeyValue label="Requested Delivery" value={formatDate(order.requested_delivery_date)} />
        <KeyValue
          label="Handed Off"
          value={
            order.handed_off_at
              ? `${formatDateTime(order.handed_off_at)} (${HANDOFF_SOURCE_LABELS[order.handoff_source ?? ''] ?? order.handoff_source})`
              : '—'
          }
        />
        <KeyValue label="Last Updated" value={formatDateTime(order.updated_at)} />
      </Card>

      {editing && (
        <Card className="space-y-4 p-6">
          <FormSectionHeading>Edit Order (Admin)</FormSectionHeading>
          <DateField label="Requested Delivery Date" value={editDate} onChange={(e) => setEditDate(e.target.value)} />
          {editLines.map((line, index) => {
            const lineId = order.lines[index]?.id
            // Unknown -> read-only; the server decides anyway.
            const quantityLocked = assessedLineIds === null
            const assessed = lineId !== undefined && assessedLineIds !== null && assessedLineIds.has(lineId)
            return (
              <div key={index} className="grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
                <div className="col-span-2 text-sm sm:col-span-1">{productsById.get(line.product_id)?.name ?? `Product ${line.product_id}`}</div>
                {quantityLocked ? (
                  <div className="flex flex-col gap-1 text-xs text-gold-100/60">
                    Quantity
                    <span className="py-2 text-sm text-gold-100" aria-label={`Line ${index + 1} quantity (read-only)`}>
                      {formatNumber(line.quantity, { maximumFractionDigits: 4 })}
                    </span>
                    <span>Fixed until its fulfilment assessment is known.</span>
                  </div>
                ) : (
                  <label className="flex flex-col gap-1 text-xs text-gold-100/60">
                    Quantity
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="any"
                      aria-label={`Line ${index + 1} quantity`}
                      className="rounded border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-gold-100"
                      value={line.quantity}
                      onChange={(e) => setEditLines((prev) => prev.map((l, i) => (i === index ? { ...l, quantity: e.target.value } : l)))}
                    />
                    {assessed && <span>Assessed at hand-off: a change needs confirmation.</span>}
                  </label>
                )}
                <label className="flex flex-col gap-1 text-xs text-gold-100/60">
                  Unit Price
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="any"
                    aria-label={`Line ${index + 1} unit price`}
                    className="rounded border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-gold-100"
                    value={line.unit_price}
                    onChange={(e) => setEditLines((prev) => prev.map((l, i) => (i === index ? { ...l, unit_price: e.target.value } : l)))}
                  />
                </label>
              </div>
            )
          })}
          {assessedQuantityChanged && (
            <CheckboxField
              label="Confirm: an assessed line's quantity changes its production demand (recomputed from the stock covered at hand-off)."
              checked={confirmDemandChange}
              onChange={(e) => setConfirmDemandChange(e.target.checked)}
            />
          )}
          <TextareaField label="Reason for the change" required value={editReason} onChange={(e) => setEditReason(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setEditing(false)} disabled={busy !== null}>Discard</Button>
            <Button onClick={saveEdit} isLoading={busy === 'edit'} disabled={busy !== null || !editReason.trim() || (assessedQuantityChanged && !confirmDemandChange)}>
              Save Changes
            </Button>
          </div>
        </Card>
      )}

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Products</FormSectionHeading>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Product</th>
                <th className="py-2 pr-3 text-right">Quantity</th>
                <th className="py-2 pr-3">Unit</th>
                <th className="py-2 pr-3 text-right">Allocated</th>
                <th className="py-2 pr-3 text-right">Delivered</th>
                <th className="py-2 pr-3 text-right">Remaining</th>
                <th className="py-2 pr-3 text-right">Unit Price</th>
                <th className="py-2 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {order.lines.map((line) => (
                <tr key={line.id} className="border-t border-ink-700">
                  <td className="py-2 pr-3">{line.line_number}</td>
                  <td className="py-2 pr-3">{productsById.get(line.product_id)?.name ?? `Product ${line.product_id}`}</td>
                  <td className="py-2 pr-3 text-right">{formatNumber(line.quantity, { maximumFractionDigits: 4 })}</td>
                  <td className="py-2 pr-3">{unitsById.get(line.unit_of_measure_id)?.code ?? '—'}</td>
                  <td className="py-2 pr-3 text-right">{formatNumber(line.allocated_quantity ?? '0', { maximumFractionDigits: 4 })}</td>
                  <td className="py-2 pr-3 text-right">{formatNumber(line.fulfilled_quantity ?? '0', { maximumFractionDigits: 4 })}</td>
                  <td className="py-2 pr-3 text-right">
                    {line.remaining_quantity == null ? '—' : formatNumber(line.remaining_quantity, { maximumFractionDigits: 4 })}
                  </td>
                  <td className="py-2 pr-3 text-right">{formatNumber(line.unit_price, { maximumFractionDigits: 4 })}</td>
                  <td className="py-2 text-right">{money(line.line_amount, order.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-col items-end gap-1 border-t border-ink-700 pt-3 text-sm">
          <div><span className="text-gold-100/50">Subtotal: </span>{money(order.subtotal_amount, order.currency)}</div>
          <div className="font-medium"><span className="text-gold-100/50">Total: </span>{money(order.total_amount, order.currency)}</div>
        </div>
      </Card>

      {deliveries !== null && (
        <Card className="space-y-3 p-6">
          <FormSectionHeading>Delivery Instructions</FormSectionHeading>
          {deliveries.length === 0 ? (
            <p className="text-sm text-gold-100/60">No deliveries yet.</p>
          ) : (
            <ul className="divide-y divide-ink-700">
              {deliveries.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    {d.delivery_number} <span className="text-gold-100/50">· {formatDateTime(d.created_at)}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    <Badge tone={DELIVERY_STATUS_TONES[d.status] ?? 'neutral'}>{DELIVERY_STATUS_LABELS[d.status] ?? d.status}</Badge>
                    <Button variant="secondary" onClick={() => navigate(`/deliveries/${d.id}`)}>Open</Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
