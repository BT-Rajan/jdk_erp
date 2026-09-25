import { useEffect, useState } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { SearchSelectField, type SearchSelectOption } from '@/components/forms/SearchSelectField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDateTime, formatNumber } from '@/lib/format'
import {
  isPositiveDecimal,
  materialLabel,
  warehouseLabel,
  type PaginatedResponse,
  type RawMaterialOption,
  type WarehouseOption,
} from './inventoryShared'

/** Mirrors backend/app/schemas/inventory.py's AdjustmentOut. */
interface AdjustmentResult {
  id: number
  material_name: string
  warehouse_name: string
  quantity: string
  unit_code: string
  reason: string
  created_by_name: string | null
  created_at: string
  quantity_on_hand: string
}

type Direction = 'in' | 'out'

interface FormState {
  raw_material_id: string
  warehouse_id: string
  direction: Direction
  quantity: string
  reason: string
}

function emptyForm(): FormState {
  return { raw_material_id: '', warehouse_id: '', direction: 'in', quantity: '', reason: '' }
}

/** Controlled Stock Adjustments (backend/app/api/inventory.py's
 * create_adjustment) -- the explicit, manual correction for a verified
 * physical/system stock difference. No listing here: the backend itself
 * exposes no way to browse past adjustments (by design -- see the
 * module's own gap-fix reports), so this page is the action alone, same
 * as FinancePaymentsPage's own "Record Payment" panel is a pure action,
 * not a CRUD form. Direction is a UI-only convenience -- the request
 * itself always sends a single signed `quantity`, exactly what the
 * backend's own movement_type-plus-sign design expects. */
export function InventoryAdjustmentsPage() {
  const [materials, setMaterials] = useState<RawMaterialOption[]>([])
  const [warehouses, setWarehouses] = useState<WarehouseOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  const [form, setForm] = useState<FormState>(emptyForm)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AdjustmentResult | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      apiClient.get<PaginatedResponse<RawMaterialOption>>('/api/raw-materials', { params: { page_size: 200 } }),
      apiClient.get<PaginatedResponse<WarehouseOption>>('/api/warehouses', { params: { page_size: 200 } }),
    ])
      .then(([materialsResponse, warehousesResponse]) => {
        if (cancelled) return
        setMaterials(materialsResponse.data.data)
        setWarehouses(warehousesResponse.data.data)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Failed to load raw materials and warehouses.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const materialOptions: SearchSelectOption[] = materials.map((m) => ({ value: String(m.id), label: materialLabel(m) }))
  const warehouseOptions: SearchSelectOption[] = warehouses.map((w) => ({ value: String(w.id), label: warehouseLabel(w) }))

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => ({ ...prev, [key]: '' }))
  }

  function validate(): boolean {
    const errors: Record<string, string> = {}
    if (!form.raw_material_id) errors.raw_material_id = 'Select a raw material.'
    if (!form.warehouse_id) errors.warehouse_id = 'Select a warehouse.'
    if (!isPositiveDecimal(form.quantity)) errors.quantity = 'Enter a quantity greater than zero.'
    if (!form.reason.trim()) errors.reason = 'A reason is required.'
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  async function submit() {
    if (!validate()) return
    setBusy(true)
    setError(null)
    try {
      const signedQuantity = form.direction === 'out' ? `-${form.quantity}` : form.quantity
      const { data } = await apiClient.post<AdjustmentResult>('/api/inventory/adjustments', {
        raw_material_id: Number(form.raw_material_id),
        warehouse_id: Number(form.warehouse_id),
        quantity: signedQuantity,
        reason: form.reason.trim(),
      })
      setResult(data)
      setForm((prev) => ({ ...emptyForm(), raw_material_id: prev.raw_material_id, warehouse_id: prev.warehouse_id }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to record the adjustment.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Stock Adjustments"
        subtitle="Correct a verified physical/system stock difference. Every adjustment is recorded as a permanent, traceable ledger entry."
      />

      <Alert variant="danger">{loadError}</Alert>

      <div className="max-w-2xl space-y-4 rounded-md border border-ink-700 p-4">
        <Alert variant="danger">{error}</Alert>
        {result && (
          <Alert variant="success">
            Adjustment recorded for {result.material_name} at {result.warehouse_name}: {result.quantity} {result.unit_code}
            {' '}({result.reason}). New balance: {formatNumber(result.quantity_on_hand)} {result.unit_code}.
            {result.created_by_name && ` Recorded by ${result.created_by_name} on ${formatDateTime(result.created_at)}.`}
          </Alert>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <SearchSelectField
            label="Raw Material"
            required
            placeholder="Type to search materials..."
            options={materialOptions}
            value={form.raw_material_id || null}
            onChange={(value) => setField('raw_material_id', value ?? '')}
            error={fieldErrors.raw_material_id}
          />
          <SearchSelectField
            label="Warehouse"
            required
            placeholder="Type to search warehouses..."
            options={warehouseOptions}
            value={form.warehouse_id || null}
            onChange={(value) => setField('warehouse_id', value ?? '')}
            error={fieldErrors.warehouse_id}
          />
          <SelectField
            label="Direction"
            required
            value={form.direction}
            onChange={(e) => setField('direction', e.target.value as Direction)}
          >
            <option value="in">Stock In (increase)</option>
            <option value="out">Stock Out (decrease)</option>
          </SelectField>
          <TextField
            label="Quantity"
            required
            type="number"
            min="0"
            step="any"
            value={form.quantity}
            onChange={(e) => setField('quantity', e.target.value)}
            error={fieldErrors.quantity}
          />
          <TextareaField
            label="Reason"
            required
            placeholder="e.g. Physical count found 12 more bags than the system showed"
            value={form.reason}
            onChange={(e) => setField('reason', e.target.value)}
            error={fieldErrors.reason}
          />
        </div>

        <div className="flex justify-end border-t border-ink-700 pt-4">
          <Button onClick={submit} isLoading={busy}>Record Adjustment</Button>
        </div>
      </div>
    </div>
  )
}
