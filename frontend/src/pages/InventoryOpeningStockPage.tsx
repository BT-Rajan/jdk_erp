import { useEffect, useState } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { SearchSelectField, type SearchSelectOption } from '@/components/forms/SearchSelectField'
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

/** Mirrors backend/app/schemas/inventory.py's OpeningStockOut. */
interface OpeningStockResult {
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

interface FormState {
  raw_material_id: string
  warehouse_id: string
  quantity: string
  reason: string
}

function emptyForm(): FormState {
  return { raw_material_id: '', warehouse_id: '', quantity: '', reason: '' }
}

/** Controlled Opening Stock (backend/app/api/inventory.py's
 * create_opening_stock) -- establishes a (raw material, warehouse)
 * pair's starting balance. Always IN, so unlike
 * InventoryAdjustmentsPage there is no Direction field -- the backend
 * itself rejects a non-positive quantity. At most one submission per
 * pair ever succeeds; a second attempt is rejected by the backend as a
 * duplicate (BUSINESS_RULE_ERROR, since the pair already has a
 * movement) or, in a genuine race, as a CONFLICT. No listing here, same
 * reasoning as InventoryAdjustmentsPage: the backend exposes no way to
 * browse past opening-stock entries. */
export function InventoryOpeningStockPage() {
  const [materials, setMaterials] = useState<RawMaterialOption[]>([])
  const [warehouses, setWarehouses] = useState<WarehouseOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  const [form, setForm] = useState<FormState>(emptyForm)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<OpeningStockResult | null>(null)
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
    if (!form.reason.trim()) errors.reason = 'A reason/description is required.'
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  async function submit() {
    if (!validate()) return
    setBusy(true)
    setError(null)
    try {
      const { data } = await apiClient.post<OpeningStockResult>('/api/inventory/opening-stock', {
        raw_material_id: Number(form.raw_material_id),
        warehouse_id: Number(form.warehouse_id),
        quantity: form.quantity,
        reason: form.reason.trim(),
      })
      setResult(data)
      setForm(emptyForm)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to record opening stock.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Opening Stock"
        subtitle="Establish a raw material's starting balance in a warehouse. Allowed once per material/warehouse pair -- use a Stock Adjustment for any later correction."
      />

      <Alert variant="danger">{loadError}</Alert>

      <div className="max-w-2xl space-y-4 rounded-md border border-ink-700 p-4">
        <Alert variant="danger">{error}</Alert>
        {result && (
          <Alert variant="success">
            Opening stock recorded for {result.material_name} at {result.warehouse_name}: {result.quantity} {result.unit_code}
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
            placeholder="e.g. Initial physical stock count at go-live"
            value={form.reason}
            onChange={(e) => setField('reason', e.target.value)}
            error={fieldErrors.reason}
          />
        </div>

        <div className="flex justify-end border-t border-ink-700 pt-4">
          <Button onClick={submit} isLoading={busy}>Record Opening Stock</Button>
        </div>
      </div>
    </div>
  )
}
