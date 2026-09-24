import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { SearchSelectField } from '@/components/forms/SearchSelectField'
import { SelectField } from '@/components/forms/SelectField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { formatDate } from '@/lib/format'
import { isPositiveDecimal, todayIso, type LookupOption, type MaterialOption, type PaginatedResponse, type Rfq } from './rfqShared'

interface ItemDraft {
  key: number
  raw_material_id: string
  quantity: string
  unit_of_measure_id: string
  remarks: string
}

interface RfqFormState {
  required_delivery_date: string
  priority: 'normal' | 'urgent'
  items: ItemDraft[]
  supplier_ids: number[]
}

let itemKey = 0
function emptyItem(): ItemDraft {
  itemKey += 1
  return { key: itemKey, raw_material_id: '', quantity: '', unit_of_measure_id: '', remarks: '' }
}

function formFromRfq(rfq: Rfq | null): RfqFormState {
  if (!rfq) {
    return { required_delivery_date: '', priority: 'normal', items: [emptyItem()], supplier_ids: [] }
  }
  return {
    required_delivery_date: rfq.required_delivery_date ?? '',
    priority: rfq.priority,
    items: rfq.lines.map((line) => ({
      ...emptyItem(),
      raw_material_id: String(line.raw_material_id),
      quantity: String(Number(line.quantity)),
      unit_of_measure_id: String(line.unit_of_measure_id),
      remarks: line.remarks ?? '',
    })),
    supplier_ids: rfq.invitations.map((i) => i.supplier_id),
  }
}

/** Client-side mirror of the server's form rules -- the server enforces
 * all of them regardless (docs/modules/rfq.md #2-#4). */
function validateForm(form: RfqFormState): string | null {
  if (!form.required_delivery_date) return 'Required By date is required.'
  if (form.required_delivery_date < todayIso()) return 'Required By date cannot be in the past.'
  if (form.items.length === 0) return 'Add at least one item.'
  for (const [index, item] of form.items.entries()) {
    const n = index + 1
    if (!item.raw_material_id) return `Item ${n}: select a product / material.`
    if (!isPositiveDecimal(item.quantity.trim())) return `Item ${n}: quantity must be greater than zero.`
    if (!item.unit_of_measure_id) return `Item ${n}: select a unit.`
  }
  if (form.supplier_ids.length === 0) return 'Select at least one supplier.'
  return null
}

function hasQuotes(rfq: Rfq): boolean {
  return rfq.invitations.some((i) => i.responses.length > 0)
}

/** New RFQ (`/rfqs/new`) and edit / revise (`/rfqs/:rfqId/edit`) as a
 * page (docs/modules/rfq.md #2-#4, #9). Save Draft keeps it editable;
 * Submit issues the next revision and generates one PDF per supplier.
 * Either way the user returns to the RFQ list with that RFQ open. */
export function RfqFormPage() {
  const { rfqId } = useParams()
  const navigate = useNavigate()
  const { user: currentUser } = useAuth()

  const [rfq, setRfq] = useState<Rfq | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [suppliers, setSuppliers] = useState<LookupOption[]>([])
  const [materials, setMaterials] = useState<MaterialOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])

  const [form, setForm] = useState<RfqFormState>(() => formFromRfq(null))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'draft' | 'submit' | null>(null)
  const [supplierPick, setSupplierPick] = useState<string | null>(null)
  const [nextNumber, setNextNumber] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError(null)
      try {
        const [suppliersResponse, materialsResponse, unitsResponse, rfqResponse] = await Promise.all([
          apiClient.get<PaginatedResponse<LookupOption>>('/api/suppliers', { params: { page_size: 200 } }),
          apiClient.get<PaginatedResponse<MaterialOption>>('/api/raw-materials', { params: { page_size: 200 } }),
          apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
          rfqId ? apiClient.get<Rfq>(`/api/rfqs/${rfqId}`) : Promise.resolve(null),
        ])
        if (cancelled) return
        setSuppliers(suppliersResponse.data.data)
        setMaterials(materialsResponse.data.data)
        setUnits(unitsResponse.data.data)
        const loaded = rfqResponse ? rfqResponse.data : null
        if (loaded && (loaded.status !== 'draft' && !(loaded.status === 'issued' && !hasQuotes(loaded)))) {
          setLoadError(`RFQ ${loaded.rfq_number} can no longer be changed.`)
        }
        setRfq(loaded)
        setForm(formFromRfq(loaded))
        if (!loaded) {
          const { data } = await apiClient.get<{ rfq_number: string }>('/api/rfqs/next-number')
          if (!cancelled) setNextNumber(data.rfq_number)
        }
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Failed to load the RFQ form.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [rfqId])

  const materialsById = useMemo(() => new Map(materials.map((m) => [m.id, m])), [materials])
  const suppliersById = useMemo(() => new Map(suppliers.map((s) => [s.id, s])), [suppliers])
  const supplierOptions = useMemo(
    () =>
      suppliers
        .filter((s) => s.is_active && !form.supplier_ids.includes(s.id))
        .map((s) => ({ value: String(s.id), label: s.code ? `${s.name} (${s.code})` : s.name })),
    [suppliers, form.supplier_ids],
  )

  const isIssued = rfq !== null && rfq.status !== 'draft'
  const nextRevision = (rfq?.revision_number ?? 0) + 1

  function updateItem(key: number, patch: Partial<ItemDraft>) {
    setForm((prev) => ({ ...prev, items: prev.items.map((item) => (item.key === key ? { ...item, ...patch } : item)) }))
  }

  function selectMaterial(key: number, materialId: string) {
    // UOM defaults from the item master; the user can pick another unit.
    const material = materialsById.get(Number(materialId))
    updateItem(key, { raw_material_id: materialId, unit_of_measure_id: material ? String(material.unit_of_measure_id) : '' })
  }

  async function save(submit: boolean) {
    const problem = validateForm(form)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setBusy(submit ? 'submit' : 'draft')
    const body = {
      submit,
      required_delivery_date: form.required_delivery_date,
      priority: form.priority,
      supplier_ids: form.supplier_ids,
      lines: form.items.map((item) => ({
        raw_material_id: Number(item.raw_material_id),
        quantity: item.quantity.trim(),
        unit_of_measure_id: Number(item.unit_of_measure_id),
        remarks: item.remarks.trim() || null,
      })),
    }
    try {
      const { data } = rfq ? await apiClient.put<Rfq>(`/api/rfqs/${rfq.id}`, body) : await apiClient.post<Rfq>('/api/rfqs', body)
      navigate(`/rfqs/${data.id}`, {
        state: {
          record: data,
          notice:
            data.status === 'draft'
              ? `RFQ ${data.rfq_number} saved as draft.`
              : `RFQ ${data.rfq_number} revision ${data.revision_number} submitted. Download or email the PDF for each supplier below.`,
        },
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(null)
    }
  }

  const title = rfq ? `${isIssued ? 'Revise' : 'Edit'} RFQ ${rfq.rfq_number}` : 'New RFQ'

  return (
    <div className="space-y-6">
      <PageHeader title={title} subtitle="Items and quantities to quote for, and the registered suppliers to ask." />

      {loading ? (
        <Spinner />
      ) : loadError ? (
        <div className="flex flex-col gap-4">
          <Alert variant="danger">{loadError}</Alert>
          <div>
            <Button variant="secondary" onClick={() => navigate('/rfqs')}>Back to RFQs</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <Alert variant="danger">{error}</Alert>
          {isIssued && (
            <Alert variant="info">Submitting creates revision {nextRevision} and a new PDF for every supplier. Earlier PDFs are kept.</Alert>
          )}

          <div className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div><span className="text-gold-100/50">RFQ Number: </span>{rfq?.rfq_number ?? nextNumber ?? '—'}</div>
            <div><span className="text-gold-100/50">RFQ Date: </span>{formatDate(rfq?.rfq_date ?? todayIso())}</div>
            <div><span className="text-gold-100/50">Requested By: </span>{rfq?.requested_by_name ?? currentUser?.full_name ?? '—'}</div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <DateField
              label="Required By"
              required
              min={todayIso()}
              value={form.required_delivery_date}
              onChange={(e) => setForm((prev) => ({ ...prev, required_delivery_date: e.target.value }))}
            />
            <SelectField
              label="Priority"
              value={form.priority}
              onChange={(e) => setForm((prev) => ({ ...prev, priority: e.target.value as RfqFormState['priority'] }))}
            >
              <option value="normal">Normal</option>
              <option value="urgent">Urgent</option>
            </SelectField>
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
                          {materials.filter((m) => m.is_active).map((m) => (
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
                          {units.filter((u) => u.is_active).map((u) => (
                            <option key={u.id} value={u.id}>{u.code}</option>
                          ))}
                        </select>
                      </td>
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
            <Button type="button" variant="secondary" className="mt-2" onClick={() => setForm((prev) => ({ ...prev, items: [...prev.items, emptyItem()] }))}>
              Add Item
            </Button>
          </div>

          <div>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-gold-100/50">Suppliers</h3>
            <SearchSelectField
              label="Add Supplier"
              placeholder="Type 2 letters of the supplier name..."
              minQueryLength={2}
              options={supplierOptions}
              value={supplierPick}
              onChange={(value) => {
                if (value) setForm((prev) => ({ ...prev, supplier_ids: [...prev.supplier_ids, Number(value)] }))
                setSupplierPick(null)
              }}
            />
            {form.supplier_ids.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {form.supplier_ids.map((id) => (
                  <span key={id} className="flex items-center gap-2 rounded border border-ink-700 px-2 py-1 text-sm">
                    {suppliersById.get(id)?.name ?? `#${id}`}
                    <button
                      type="button"
                      aria-label={`Remove ${suppliersById.get(id)?.name ?? id}`}
                      className="text-gold-100/60 hover:text-gold-100"
                      onClick={() => setForm((prev) => ({ ...prev, supplier_ids: prev.supplier_ids.filter((s) => s !== id) }))}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-ink-700 pt-4">
            <Button variant="secondary" onClick={() => navigate('/rfqs')}>Cancel</Button>
            {!isIssued && (
              <Button variant="secondary" onClick={() => save(false)} isLoading={busy === 'draft'} disabled={busy !== null}>
                Save Draft
              </Button>
            )}
            <Button onClick={() => save(true)} isLoading={busy === 'submit'} disabled={busy !== null}>
              {isIssued ? `Submit Revision ${nextRevision}` : 'Submit & Generate PDF'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
