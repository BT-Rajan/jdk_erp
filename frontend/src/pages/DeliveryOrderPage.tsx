import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { KeyValue } from '@/components/ui/KeyValue'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatDateTime, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import { ORDER_STATUS_LABELS, ORDER_STATUS_TONES } from './quotationShared'
import {
  DELIVERY_STATUS_LABELS,
  DELIVERY_STATUS_TONES,
  type DeliveryInstruction,
  type DeliveryPosition,
} from './deliveryShared'

const qty = (value: string) => formatNumber(value, { maximumFractionDigits: 4 })

/** One Sales Order's delivery position and its Delivery Instructions
 * (`/deliveries/orders/:orderId`), and the form for a new instruction.
 * The shipment quantity entered here is this delivery's quantity -- the
 * Sales Order quantity never changes. Eligibility and every limit are
 * the server's; the page only shows what it reports. */
export function DeliveryOrderPage() {
  const { orderId } = useParams()
  const navigate = useNavigate()
  const [position, setPosition] = useState<DeliveryPosition | null>(null)
  const [instructions, setInstructions] = useState<DeliveryInstruction[]>([])
  const [products, setProducts] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [denied, setDenied] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)
  // Shipment quantity per Sales Order line id; blank = not in this delivery.
  const [shipment, setShipment] = useState<Record<number, string>>({})

  const load = useCallback(async () => {
    const [p, list] = await Promise.all([
      apiClient.get<DeliveryPosition>('/api/delivery-instructions/position', { params: { sales_order_id: orderId } }),
      apiClient.get<PaginatedResponse<DeliveryInstruction>>('/api/delivery-instructions', {
        params: { sales_order_id: orderId, page_size: 100 },
      }),
    ])
    setPosition(p.data)
    setInstructions(list.data.data)
  }, [orderId])

  useEffect(() => {
    load().catch((err) => {
      if (err instanceof ApiError && err.status === 403) setDenied(true)
      else setLoadError(err instanceof ApiError ? err.message : 'Failed to load the delivery position.')
    })
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

  const enteredLines = Object.entries(shipment)
    .filter(([, value]) => value.trim() !== '')
    .map(([lineId, value]) => ({ sales_order_line_id: Number(lineId), quantity: value.trim() }))

  async function create() {
    setBusy(true)
    setActionError(null)
    try {
      const { data } = await apiClient.post<DeliveryInstruction>('/api/delivery-instructions', {
        sales_order_id: Number(orderId),
        lines: enteredLines,
      })
      navigate(`/deliveries/${data.id}`)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (denied) return <AccessDeniedState message="Deliveries need the warehouse delivery permission." />
  if (loadError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Delivery" />
        <Alert variant="danger">{loadError}</Alert>
        <Button variant="secondary" onClick={() => navigate('/deliveries')}>Back to Deliveries</Button>
      </div>
    )
  }
  if (!position) return <Spinner />

  const productName = (id: number) => productsById.get(id)?.name ?? `Product ${id}`
  const unitCode = (id: number) => unitsById.get(id)?.code ?? '—'

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Deliver ${position.sales_order_number}`}
        subtitle={position.customer_name ?? undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate('/deliveries')}>All Deliveries</Button>
            {position.can_create && !creating && <Button onClick={() => setCreating(true)}>New Delivery Instruction</Button>}
          </div>
        }
      />

      <Alert variant="danger">{actionError}</Alert>

      <Card className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
        <KeyValue label="Order Status">
          <Badge tone={ORDER_STATUS_TONES[position.sales_order_status] ?? 'neutral'}>
            {ORDER_STATUS_LABELS[position.sales_order_status] ?? position.sales_order_status}
          </Badge>
        </KeyValue>
        <KeyValue label="Customer" value={position.customer_name ?? '—'} />
        <KeyValue label="Requested Delivery" value={formatDate(position.requested_delivery_date)} />
        <KeyValue
          label="Delivery Allowance"
          value={`${formatNumber(position.scrap_allowance_percent, { maximumFractionDigits: 2 })}% ${position.allowance_locked ? '(locked)' : '(current setting)'}`}
        />
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>{creating ? 'New Delivery Instruction' : 'Delivery Position'}</FormSectionHeading>
        {creating && (
          <p className="text-sm text-gold-100/60">
            Enter the quantity to ship in this delivery for each product it includes. Leave a product blank to leave it out.
            The Sales Order quantity is not changed.
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                <th className="py-2 pr-3">Product</th>
                <th className="py-2 pr-3">Unit</th>
                <th className="py-2 pr-3 text-right">Ordered</th>
                <th className="py-2 pr-3 text-right">Delivered</th>
                <th className="py-2 pr-3 text-right">Remaining</th>
                <th className="py-2 pr-3 text-right">Allowed Total</th>
                <th className="py-2 pr-3 text-right">May Still Deliver</th>
                {creating && <th className="py-2 text-right">Ship Now</th>}
              </tr>
            </thead>
            <tbody>
              {position.lines.map((line) => (
                <tr key={line.sales_order_line_id} className="border-t border-ink-700">
                  <td className="py-2 pr-3">{productName(line.product_id)}</td>
                  <td className="py-2 pr-3">{unitCode(line.unit_of_measure_id)}</td>
                  <td className="py-2 pr-3 text-right">{qty(line.ordered_quantity)}</td>
                  <td className="py-2 pr-3 text-right">{qty(line.fulfilled_quantity)}</td>
                  <td className="py-2 pr-3 text-right">{qty(line.remaining_quantity)}</td>
                  <td className="py-2 pr-3 text-right">{qty(line.ceiling_quantity)}</td>
                  <td className="py-2 pr-3 text-right">{qty(line.remaining_permitted_quantity)}</td>
                  {creating && (
                    <td className="py-2 text-right">
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="any"
                        aria-label={`Ship now: ${productName(line.product_id)}`}
                        className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-right text-sm text-gold-100"
                        value={shipment[line.sales_order_line_id] ?? ''}
                        onChange={(e) => setShipment((prev) => ({ ...prev, [line.sales_order_line_id]: e.target.value }))}
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {creating && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setCreating(false)} disabled={busy}>Discard</Button>
            <Button onClick={create} isLoading={busy} disabled={busy || enteredLines.length === 0}>Create Delivery Instruction</Button>
          </div>
        )}
        {!position.can_create && (
          <p className="text-sm text-gold-100/60">This Sales Order cannot take a new delivery in its current status.</p>
        )}
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Delivery Instructions</FormSectionHeading>
        {instructions.length === 0 ? (
          <p className="text-sm text-gold-100/60">No deliveries yet for this order.</p>
        ) : (
          <ul className="divide-y divide-ink-700">
            {instructions.map((instruction) => (
              <li key={instruction.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>
                  {instruction.delivery_number} <span className="text-gold-100/50">· {formatDateTime(instruction.created_at)}</span>
                </span>
                <span className="flex items-center gap-2">
                  <Badge tone={DELIVERY_STATUS_TONES[instruction.status] ?? 'neutral'}>
                    {DELIVERY_STATUS_LABELS[instruction.status] ?? instruction.status}
                  </Badge>
                  <Button variant="secondary" onClick={() => navigate(`/deliveries/${instruction.id}`)}>Open</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
