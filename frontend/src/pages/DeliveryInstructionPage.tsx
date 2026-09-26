import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { KeyValue } from '@/components/ui/KeyValue'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { formatDateTime, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import {
  DELIVERY_STATUS_LABELS,
  DELIVERY_STATUS_TONES,
  type DeliveryInstruction,
  type DeliveryPosition,
} from './deliveryShared'

interface LineEdit {
  quantity: string
  pallets: string
}

const qty = (value: string) => formatNumber(value, { maximumFractionDigits: 4 })

/** One Delivery Instruction (`/deliveries/:instructionId`). While pending,
 * the warehouse may change each line's shipment quantity and pallets,
 * fulfil it (issuing the stock) or mark it not fulfilled with a reason;
 * a not-fulfilled instruction may be retried. The server enforces every
 * limit, the stock and each transition -- the page never decides one. */
export function DeliveryInstructionPage() {
  const { instructionId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = isAdminRole(user?.role)
  const [instruction, setInstruction] = useState<DeliveryInstruction | null>(null)
  const [position, setPosition] = useState<DeliveryPosition | null>(null)
  const [products, setProducts] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [denied, setDenied] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [edits, setEdits] = useState<Record<number, LineEdit>>({})
  const [overrideReason, setOverrideReason] = useState('')
  const [confirmingFulfil, setConfirmingFulfil] = useState(false)
  const [failing, setFailing] = useState(false)
  const [failReason, setFailReason] = useState('')

  const load = useCallback(async () => {
    const { data } = await apiClient.get<DeliveryInstruction>(`/api/delivery-instructions/${instructionId}`)
    setInstruction(data)
    const p = await apiClient.get<DeliveryPosition>('/api/delivery-instructions/position', {
      params: { sales_order_id: data.sales_order_id },
    })
    setPosition(p.data)
  }, [instructionId])

  useEffect(() => {
    load().catch((err) => {
      if (err instanceof ApiError && err.status === 403) setDenied(true)
      else setLoadError(err instanceof ApiError ? err.message : 'Failed to load the delivery instruction.')
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
  const positionByLine = useMemo(
    () => new Map((position?.lines ?? []).map((l) => [l.sales_order_line_id, l])),
    [position],
  )

  async function run(name: string, action: () => Promise<unknown>) {
    setBusy(name)
    setActionError(null)
    try {
      await action()
      setEditing(false)
      setConfirmingFulfil(false)
      setFailing(false)
      await load()
    } catch (err) {
      setConfirmingFulfil(false)
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
      await load().catch(() => undefined)
    } finally {
      setBusy(null)
    }
  }

  function startEdit() {
    if (!instruction) return
    setEdits(
      Object.fromEntries(
        instruction.lines.map((line) => [
          line.id,
          { quantity: String(Number(line.quantity)), pallets: line.pallet_count === null ? '' : String(line.pallet_count) },
        ]),
      ),
    )
    setOverrideReason('')
    setEditing(true)
  }

  // Each changed line is sent on its own; only what changed is sent.
  const saveEdits = () =>
    run('edit', async () => {
      if (!instruction) return
      for (const line of instruction.lines) {
        const edit = edits[line.id]
        if (!edit) continue
        const body: Record<string, unknown> = {}
        if (Number(edit.quantity) !== Number(line.quantity)) {
          body.quantity = edit.quantity.trim()
          if (isAdmin && overrideReason.trim()) body.override_reason = overrideReason.trim()
        }
        const pallets = edit.pallets.trim()
        if (pallets !== (line.pallet_count === null ? '' : String(line.pallet_count))) {
          body.pallet_count = pallets === '' ? null : Number(pallets)
        }
        if (Object.keys(body).length > 0) {
          await apiClient.patch(`/api/delivery-instructions/${instruction.id}/lines/${line.id}`, body)
        }
      }
    })

  const fulfil = () => run('fulfil', () => apiClient.post(`/api/delivery-instructions/${instructionId}/fulfil`))
  const markNotFulfilled = () =>
    run('fail', () => apiClient.post(`/api/delivery-instructions/${instructionId}/not-fulfilled`, { reason: failReason }))
  const retry = () => run('retry', () => apiClient.post(`/api/delivery-instructions/${instructionId}/retry`))

  if (denied) return <AccessDeniedState message="Deliveries need the warehouse delivery permission." />
  if (loadError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Delivery Instruction" />
        <Alert variant="danger">{loadError}</Alert>
        <Button variant="secondary" onClick={() => navigate('/deliveries')}>Back to Deliveries</Button>
      </div>
    )
  }
  if (!instruction) return <Spinner />

  const pending = instruction.status === 'pending'
  const productName = (id: number) => productsById.get(id)?.name ?? `Product ${id}`
  const unitCode = (id: number) => unitsById.get(id)?.code ?? '—'

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Delivery ${instruction.delivery_number}`}
        subtitle={instruction.customer_name ?? undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate(`/deliveries/orders/${instruction.sales_order_id}`)}>
              Order Deliveries
            </Button>
            {pending && !editing && !failing && (
              <>
                <Button variant="secondary" onClick={startEdit}>Edit Shipment</Button>
                <Button variant="danger" onClick={() => setFailing(true)}>Not Fulfilled</Button>
                <Button onClick={() => setConfirmingFulfil(true)}>Fulfil</Button>
              </>
            )}
            {instruction.status === 'not_fulfilled' && (
              <Button onClick={retry} isLoading={busy === 'retry'} disabled={busy !== null}>Retry Delivery</Button>
            )}
          </div>
        }
      />

      <Alert variant="danger">{actionError}</Alert>
      {instruction.status === 'not_fulfilled' && instruction.not_fulfilled_reason && (
        <Alert variant="danger">Not fulfilled: {instruction.not_fulfilled_reason}</Alert>
      )}

      <Card className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2 lg:grid-cols-3">
        <KeyValue label="Status">
          <Badge tone={DELIVERY_STATUS_TONES[instruction.status] ?? 'neutral'}>
            {DELIVERY_STATUS_LABELS[instruction.status] ?? instruction.status}
          </Badge>
        </KeyValue>
        <KeyValue label="Sales Order" value={instruction.sales_order_number ?? '—'} />
        <KeyValue label="Customer" value={instruction.customer_name ?? '—'} />
        <KeyValue label="Created" value={formatDateTime(instruction.created_at)} />
        <KeyValue label="Fulfilled" value={instruction.fulfilled_at ? formatDateTime(instruction.fulfilled_at) : '—'} />
        <KeyValue label="Not Fulfilled" value={instruction.not_fulfilled_at ? formatDateTime(instruction.not_fulfilled_at) : '—'} />
      </Card>

      {failing && (
        <Card className="space-y-3 p-6">
          <FormSectionHeading>Mark Not Fulfilled</FormSectionHeading>
          <p className="text-sm text-gold-100/60">No stock moves. The delivery can be retried later.</p>
          <TextareaField label="Reason" required value={failReason} onChange={(e) => setFailReason(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setFailing(false)} disabled={busy !== null}>Keep Pending</Button>
            <Button variant="danger" onClick={markNotFulfilled} isLoading={busy === 'fail'} disabled={busy !== null || !failReason.trim()}>
              Confirm Not Fulfilled
            </Button>
          </div>
        </Card>
      )}

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Shipment</FormSectionHeading>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                <th className="py-2 pr-3">Product</th>
                <th className="py-2 pr-3 text-right">Order Qty</th>
                <th className="py-2 pr-3 text-right">Ship Qty</th>
                <th className="py-2 pr-3">Unit</th>
                <th className="py-2 pr-3 text-right">Pallets (default)</th>
                <th className="py-2 text-right">Pallets</th>
              </tr>
            </thead>
            <tbody>
              {instruction.lines.map((line) => {
                const edit = edits[line.id]
                return (
                  <tr key={line.id} className="border-t border-ink-700 align-top">
                    <td className="py-2 pr-3">
                      {productName(line.product_id)}
                      {line.quantity_override_reason && (
                        <div className="text-xs text-gold-100/50">Override: {line.quantity_override_reason}</div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right">{qty(line.ordered_quantity)}</td>
                    <td className="py-2 pr-3 text-right">
                      {editing && edit ? (
                        <input
                          type="number"
                          inputMode="decimal"
                          min="0"
                          step="any"
                          aria-label={`Ship quantity: ${productName(line.product_id)}`}
                          className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-right text-sm text-gold-100"
                          value={edit.quantity}
                          onChange={(e) => setEdits((prev) => ({ ...prev, [line.id]: { ...edit, quantity: e.target.value } }))}
                        />
                      ) : (
                        qty(line.quantity)
                      )}
                    </td>
                    <td className="py-2 pr-3">{unitCode(line.unit_of_measure_id)}</td>
                    <td className="py-2 pr-3 text-right">{line.pallet_count_default ?? '—'}</td>
                    <td className="py-2 text-right">
                      {editing && edit ? (
                        <input
                          type="number"
                          inputMode="numeric"
                          min="1"
                          step="1"
                          aria-label={`Pallets: ${productName(line.product_id)}`}
                          className="w-20 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-right text-sm text-gold-100"
                          value={edit.pallets}
                          onChange={(e) => setEdits((prev) => ({ ...prev, [line.id]: { ...edit, pallets: e.target.value } }))}
                        />
                      ) : (
                        <>
                          {line.pallet_count ?? '—'}
                          {line.pallet_count_manual && <span className="text-xs text-gold-100/50"> (manual)</span>}
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {editing && (
          <div className="space-y-3">
            {isAdmin && (
              <TextareaField
                label="Override reason (Admin, only if a quantity exceeds what may still be delivered)"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
              />
            )}
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => setEditing(false)} disabled={busy !== null}>Discard</Button>
              <Button onClick={saveEdits} isLoading={busy === 'edit'} disabled={busy !== null}>Save Shipment</Button>
            </div>
          </div>
        )}
      </Card>

      <Modal
        open={confirmingFulfil}
        title={`Fulfil ${instruction.delivery_number}?`}
        onClose={() => setConfirmingFulfil(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmingFulfil(false)} disabled={busy !== null}>Cancel</Button>
            <Button onClick={fulfil} isLoading={busy === 'fulfil'}>Confirm Fulfilment</Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-gold-100/80">
          <p>These quantities will be issued from Finished Goods stock. This cannot be undone.</p>
          <ul className="space-y-2">
            {instruction.lines.map((line) => {
              const pos = positionByLine.get(line.sales_order_line_id)
              return (
                <li key={line.id}>
                  <span className="font-medium text-gold-100">
                    {productName(line.product_id)}: {qty(line.quantity)} {unitCode(line.unit_of_measure_id)}
                  </span>
                  {pos && (
                    <div className="text-xs text-gold-100/60">
                      Ordered {qty(pos.ordered_quantity)} · delivered {qty(pos.fulfilled_quantity)} · may still deliver{' '}
                      {qty(pos.remaining_permitted_quantity)}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      </Modal>
    </div>
  )
}
