import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { SearchSelectField } from '@/components/forms/SearchSelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate } from '@/lib/format'
import { isPositiveDecimal, todayIso, type LookupOption, type PaginatedResponse } from './rfqShared'

/** The parts of backend/app/schemas/purchase_order.py this form uses. */
interface PoLine {
  id: number
  raw_material_id: number
  quantity: string
  unit_of_measure_id: number
  unit_price: string
  remarks: string | null
}

interface Po {
  id: number
  po_number: string
  supplier_id: number
  status: string
  order_date: string
  expected_delivery_date: string | null
  payment_terms: string | null
  currency: string
  supplier_reference: string | null
  delivery_instructions: string | null
  notes: string | null
  lines: PoLine[]
}

interface MaterialOption extends LookupOption {
  unit_of_measure_id: number
  reference_cost: string | null
}

interface ItemDraft {
  key: number
  line_id: number | null
  raw_material_id: string
  quantity: string
  unit_of_measure_id: string
  unit_price: string
  remarks: string
}

interface PoFormState {
  supplier_id: string
  expected_delivery_date: string
  payment_terms: string
  supplier_reference: string
  delivery_instructions: string
  notes: string
  items: ItemDraft[]
}

let itemKey = 0
function emptyItem(): ItemDraft {
  itemKey += 1
  return { key: itemKey, line_id: null, raw_material_id: '', quantity: '', unit_of_measure_id: '', unit_price: '', remarks: '' }
}

function formFromPo(po: Po | null): PoFormState {
  if (!po) {
    return {
      supplier_id: '',
      expected_delivery_date: '',
      payment_terms: '',
      supplier_reference: '',
      delivery_instructions: '',
      notes: '',
      items: [emptyItem()],
    }
  }
  return {
    supplier_id: String(po.supplier_id),
    expected_delivery_date: po.expected_delivery_date ?? '',
    payment_terms: po.payment_terms ?? '',
    supplier_reference: po.supplier_reference ?? '',
    delivery_instructions: po.delivery_instructions ?? '',
    notes: po.notes ?? '',
    items: po.lines.map((line) => ({
      ...emptyItem(),
      line_id: line.id,
      raw_material_id: String(line.raw_material_id),
      quantity: String(Number(line.quantity)),
      unit_of_measure_id: String(line.unit_of_measure_id),
      unit_price: String(Number(line.unit_price)),
      remarks: line.remarks ?? '',
    })),
  }
}

/** Client-side mirror of the server's rules -- the server enforces all of
 * them regardless (docs/modules/purchase_orders.md #2-#3). */
function validateForm(form: PoFormState, submit: boolean): string | null {
  if (!form.supplier_id) return 'Supplier is required.'
  if (!form.expected_delivery_date) return 'Expected delivery date is required.'
  if (form.expected_delivery_date < todayIso()) return 'Expected delivery date cannot be in the past.'
  if (!form.payment_terms.trim()) return 'Payment terms are required.'
  if (submit && form.items.length === 0) return 'Add at least one item.'
  for (const [index, item] of form.items.entries()) {
    const n = index + 1
    if (!item.raw_material_id) return `Item ${n}: select a product / material.`
    if (!isPositiveDecimal(item.quantity.trim())) return `Item ${n}: quantity must be greater than zero.`
    if (!item.unit_of_measure_id) return `Item ${n}: select a unit.`
    if (!isPositiveDecimal(item.unit_price.trim())) return `Item ${n}: unit price must be greater than zero.`
  }
  return null
}

function lineTotal(item: ItemDraft): string {
  const total = Number(item.quantity) * Number(item.unit_price)
  return Number.isFinite(total) && total > 0 ? total.toFixed(3) : '—'
}

/** New purchase order (`/purchase-orders/new`) and edit of a draft
 * (`/purchase-orders/:purchaseOrderId/edit`) as one page: header and items
 * together. Save Draft keeps it editable; Submit for Approval saves and
 * submits. Either way the user returns to the list with that PO open. */
export function PurchaseOrderFormPage() {
  const { purchaseOrderId } = useParams()
  const navigate = useNavigate()

  const [po, setPo] = useState<Po | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [suppliers, setSuppliers] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<MaterialOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])

  const [form, setForm] = useState<PoFormState>(() => formFromPo(null))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'draft' | 'submit' | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError(null)
      try {
        const [suppliersResponse, materialsResponse, unitsResponse, poResponse] = await Promise.all([
          apiClient.get<PaginatedResponse<LookupOption>>('/api/suppliers', { params: { page_size: 200 } }),
          apiClient.get<PaginatedResponse<MaterialOption>>('/api/raw-materials', { params: { page_size: 200 } }),
          apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
          purchaseOrderId ? apiClient.get<Po>(`/api/purchase-orders/${purchaseOrderId}`) : Promise.resolve(null),
        ])
        if (cancelled) return
        setSuppliers(suppliersResponse.data.data)
        setMaterials(materialsResponse.data.data)
        setUnits(unitsResponse.data.data)
        const loaded = poResponse ? poResponse.data : null
        if (loaded && loaded.status !== 'draft') {
          setLoadError(`Purchase Order ${loaded.po_number} can no longer be changed. Use Create Revision to edit it.`)
        }
        setPo(loaded)
        setForm(formFromPo(loaded))
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Failed to load the purchase order form.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [purchaseOrderId])

  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])
  const supplierOptions = useMemo(
    () =>
      suppliers
        .filter((s) => s.is_active || String(s.id) === form.supplier_id)
        .map((s) => ({ value: String(s.id), label: s.code ? `${s.name} (${s.code})` : s.name })),
    [suppliers, form.supplier_id],
  )
  const orderTotal = form.items.reduce((sum, item) => {
    const total = Number(item.quantity) * Number(item.unit_price)
    return Number.isFinite(total) && total > 0 ? sum + total : sum
  }, 0)

  function setField<K extends keyof PoFormState>(field: K, value: PoFormState[K]) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  function updateItem(key: number, patch: Partial<ItemDraft>) {
    setForm((prev) => ({ ...prev, items: prev.items.map((item) => (item.key === key ? { ...item, ...patch } : item)) }))
  }

  function selectMaterial(key: number, materialId: string) {
    // Purchase UOM defaults from the item master; price from its reference cost.
    const material = materialsById.get(Number(materialId))
    updateItem(key, {
      raw_material_id: materialId,
      unit_of_measure_id: material ? String(material.unit_of_measure_id) : '',
      ...(material?.reference_cost ? { unit_price: String(Number(material.reference_cost)) } : {}),
    })
  }

  /** Saves the header, then brings the lines in line with the form. The
   * created PO is kept in state, so retrying after a failed line never
   * creates a second PO. */
  async function persist(): Promise<Po> {
    const header = {
      expected_delivery_date: form.expected_delivery_date,
      payment_terms: form.payment_terms.trim(),
      supplier_reference: form.supplier_reference.trim() || null,
      delivery_instructions: form.delivery_instructions.trim() || null,
      notes: form.notes.trim() || null,
    }
    let saved: Po
    if (po) {
      saved = (await apiClient.patch<Po>(`/api/purchase-orders/${po.id}`, header)).data
    } else {
      saved = (
        await apiClient.post<Po>('/api/purchase-orders', {
          ...header,
          supplier_id: Number(form.supplier_id),
        })
      ).data
      setPo(saved)
    }
    const base = `/api/purchase-orders/${saved.id}/lines`
    const existing = new Map(saved.lines.map((line) => [line.id, line]))
    const kept = new Set<number>()
    const items: ItemDraft[] = []
    for (const item of form.items) {
      const body = {
        quantity: item.quantity.trim(),
        unit_of_measure_id: Number(item.unit_of_measure_id),
        unit_price: item.unit_price.trim(),
        remarks: item.remarks.trim() || null,
      }
      const current = item.line_id ? existing.get(item.line_id) : undefined
      // A line's material is fixed server-side, so a changed material is a new line.
      if (current && String(current.raw_material_id) === item.raw_material_id) {
        kept.add(current.id)
        saved = (await apiClient.patch<Po>(`${base}/${current.id}`, body)).data
        items.push(item)
      } else {
        const before = new Set(saved.lines.map((line) => line.id))
        saved = (await apiClient.post<Po>(base, { ...body, raw_material_id: Number(item.raw_material_id) })).data
        const added = saved.lines.find((line) => !before.has(line.id))
        if (added) kept.add(added.id)
        items.push({ ...item, line_id: added?.id ?? null })
      }
    }
    for (const line of existing.values()) {
      if (!kept.has(line.id)) await apiClient.delete(`${base}/${line.id}`)
    }
    setForm((prev) => ({ ...prev, items }))
    return saved
  }

  async function save(submit: boolean) {
    const problem = validateForm(form, submit)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setBusy(submit ? 'submit' : 'draft')
    try {
      const saved = await persist()
      if (submit) await apiClient.post(`/api/purchase-orders/${saved.id}/submit`)
      navigate(`/purchase-orders/${saved.id}`, {
        state: {
          notice: submit
            ? `Purchase Order ${saved.po_number} submitted for approval.`
            : `Purchase Order ${saved.po_number} saved as draft.`,
        },
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(null)
    }
  }

  const title = po ? `Edit Purchase Order ${po.po_number}` : 'New Purchase Order'
  const locked = po !== null

  return (
    <div className="space-y-6">
      <PageHeader title={title} subtitle="Supplier, delivery and payment terms, and the items to order." />

      {loading ? (
        <Spinner />
      ) : loadError ? (
        <div className="flex flex-col gap-4">
          <Alert variant="danger">{loadError}</Alert>
          <div>
            <Button variant="secondary" onClick={() => navigate('/purchase-orders')}>Back to Purchase Orders</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <Alert variant="danger">{error}</Alert>

          <div className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
            <div><span className="text-gold-100/50">PO Number: </span>{po?.po_number ?? 'Assigned on save'}</div>
            <div><span className="text-gold-100/50">PO Date: </span>{formatDate(po?.order_date ?? todayIso())}</div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {locked ? (
              <div className="text-sm">
                <span className="text-gold-100/50">Supplier: </span>
                {suppliers.find((s) => String(s.id) === form.supplier_id)?.name ?? `#${form.supplier_id}`}
              </div>
            ) : (
              <SearchSelectField
                label="Supplier"
                required
                placeholder="Type 2 letters of the supplier name..."
                minQueryLength={2}
                options={supplierOptions}
                value={form.supplier_id || null}
                onChange={(value) => setField('supplier_id', value ?? '')}
              />
            )}
            <DateField
              label="Expected Delivery Date"
              required
              min={todayIso()}
              value={form.expected_delivery_date}
              onChange={(e) => setField('expected_delivery_date', e.target.value)}
            />
            <TextField
              label="Payment Terms"
              required
              hint="e.g. Advance, 30 days, Payment on delivery."
              value={form.payment_terms}
              onChange={(e) => setField('payment_terms', e.target.value)}
            />
            <TextField
              label="Supplier Reference"
              hint="Supplier's quotation / reference number."
              value={form.supplier_reference}
              onChange={(e) => setField('supplier_reference', e.target.value)}
            />
          </div>

          <div>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Items</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
                    <th className="py-2 pr-2">Product / Material *</th>
                    <th className="py-2 pr-2">Quantity *</th>
                    <th className="py-2 pr-2">UOM *</th>
                    <th className="py-2 pr-2">Unit Price *</th>
                    <th className="py-2 pr-2">Line Total</th>
                    <th className="py-2 pr-2">Specification / Remarks</th>
                    <th className="py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {form.items.map((item, index) => (
                    <tr key={item.key} className="border-t border-ink-700 align-top">
                      <td className="py-2 pr-2">
                        <select
                          aria-label={`Item ${index + 1} product / material`}
                          className="w-56 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={item.raw_material_id}
                          onChange={(e) => selectMaterial(item.key, e.target.value)}
                        >
                          <option value="">Select...</option>
                          {materials.filter((m) => m.is_active || String(m.id) === item.raw_material_id).map((m) => (
                            <option key={m.id} value={m.id}>{m.name}{m.code ? ` (${m.code})` : ''}</option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2 pr-2">
                        <input
                          type="number"
                          min="0"
                          step="any"
                          aria-label={`Item ${index + 1} quantity`}
                          className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={item.quantity}
                          onChange={(e) => updateItem(item.key, { quantity: e.target.value })}
                        />
                      </td>
                      <td className="py-2 pr-2">
                        <select
                          aria-label={`Item ${index + 1} unit`}
                          className="w-24 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={item.unit_of_measure_id}
                          onChange={(e) => updateItem(item.key, { unit_of_measure_id: e.target.value })}
                        >
                          <option value="">Unit...</option>
                          {units.filter((u) => u.is_active || String(u.id) === item.unit_of_measure_id).map((u) => (
                            <option key={u.id} value={u.id}>{u.code}</option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2 pr-2">
                        <input
                          type="number"
                          min="0"
                          step="any"
                          aria-label={`Item ${index + 1} unit price`}
                          className="w-28 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={item.unit_price}
                          onChange={(e) => updateItem(item.key, { unit_price: e.target.value })}
                        />
                      </td>
                      <td className="py-2 pr-2 whitespace-nowrap">{lineTotal(item)}</td>
                      <td className="py-2 pr-2">
                        <input
                          type="text"
                          aria-label={`Item ${index + 1} remarks`}
                          className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1 text-sm"
                          value={item.remarks}
                          onChange={(e) => updateItem(item.key, { remarks: e.target.value })}
                        />
                      </td>
                      <td className="py-2 text-right">
                        <Button
                          variant="secondary"
                          disabled={form.items.length === 1}
                          onClick={() => setForm((prev) => ({ ...prev, items: prev.items.filter((i) => i.key !== item.key) }))}
                        >
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <Button type="button" variant="secondary" onClick={() => setForm((prev) => ({ ...prev, items: [...prev.items, emptyItem()] }))}>
                Add Item
              </Button>
              <span className="text-sm"><span className="text-gold-100/50">Total: </span>{orderTotal.toFixed(3)} {po?.currency ?? 'KWD'}</span>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <TextareaField
              label="Delivery Instructions"
              value={form.delivery_instructions}
              onChange={(e) => setField('delivery_instructions', e.target.value)}
            />
            <TextareaField label="Notes" value={form.notes} onChange={(e) => setField('notes', e.target.value)} />
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-ink-700 pt-4">
            <Button variant="secondary" onClick={() => navigate('/purchase-orders')}>Cancel</Button>
            <Button variant="secondary" onClick={() => save(false)} isLoading={busy === 'draft'} disabled={busy !== null}>
              Save Draft
            </Button>
            <Button onClick={() => save(true)} isLoading={busy === 'submit'} disabled={busy !== null}>
              Submit for Approval
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
