import { useCallback, useEffect, useMemo, useState } from 'react'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import { CheckboxField } from '@/components/forms/CheckboxField'
import { DateField } from '@/components/forms/DateField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'
import { PlanScheduleDialog } from './ProductionSchedulePage'

/** Mirror backend/app/api/production_plans.py. Every figure is the
 * server's; this page decides nothing. */
export interface MaterialNeed {
  raw_material_id: number
  raw_material_name: string
  unit_code: string | null
  required_quantity: string
  on_hand_quantity: string
  committed_quantity: string
  available_quantity: string
  shortage_quantity: string
  unit_mismatch: boolean
}

export interface MrpRow {
  demand_type: 'customer_demand' | 'independent'
  product_id: number
  product_name: string
  unit_of_measure_id: number
  production_requirement_id: number | null
  requirement_status: string | null
  sales_order_number: string | null
  line_number: number | null
  required_by_date: string | null
  required_quantity: string | null
  allocated_quantity: string | null
  outstanding_quantity: string
  fg_on_hand: string
  fg_allocated: string
  fg_free: string
  planned_quantity: string
  proposed_quantity: string
  excess_quantity: string
  plan_ids: number[]
  plan_status: string
  bom_status: string
  materials: MaterialNeed[]
  exceptions: string[]
}

export interface ProductionPlan {
  id: number
  product_id: number
  product_name: string | null
  unit_of_measure_id: number
  planned_quantity: string
  original_quantity: string
  source_type: 'customer_demand' | 'independent'
  production_requirement_id: number | null
  sales_order_number: string | null
  required_by_date: string | null
  notes: string | null
  status: 'draft' | 'planned' | 'cancelled'
  bom_id: number | null
  cancellation_reason: string | null
}

const qty = (value: string | null) => (value === null ? '—' : formatNumber(value, { maximumFractionDigits: 4 }))

const PLAN_STATUS_LABELS: Record<string, string> = {
  unplanned: 'Unplanned',
  partially_planned: 'Partly planned',
  draft: 'Draft',
  planned: 'Planned',
  cancelled: 'Cancelled',
}
const PLAN_STATUS_TONES: Record<string, BadgeTone> = {
  unplanned: 'warning',
  partially_planned: 'warning',
  draft: 'info',
  planned: 'success',
  cancelled: 'neutral',
}
const EXCEPTION_LABELS: Record<string, string> = {
  bom_required: 'BOM required',
  material_shortage: 'Material short',
  unit_mismatch: 'Unit mismatch',
  demand_cancelled: 'Demand cancelled',
  demand_satisfied: 'Demand satisfied',
}

interface Filters {
  required_by_from: string
  required_by_to: string
  product_id: string
  demand_type: string
  plan_status: string
  exception: string
}
const NO_FILTERS: Filters = { required_by_from: '', required_by_to: '', product_id: '', demand_type: '', plan_status: '', exception: '' }

type Dialog =
  | { kind: 'customer'; row: MrpRow }
  | { kind: 'independent' }
  | { kind: 'edit'; plan: ProductionPlan }
  | { kind: 'cancel'; plan: ProductionPlan }
  | { kind: 'materials'; row: MrpRow }
  | null

/** Production -> Planning (P3, MRP): what needs to be produced, how much
 * and why. Customer demand (Production Requirements, net of allocated FG)
 * and independent production, with FG, BOM and raw-material position.
 * Plans are decisions only -- nothing here produces, schedules or moves
 * stock. Needs production:view; changes need production:manage (the
 * server refuses otherwise). */
export function ProductionPlanningPage() {
  const [rows, setRows] = useState<MrpRow[]>([])
  const [summary, setSummary] = useState<MaterialNeed[]>([])
  const [plans, setPlans] = useState<ProductionPlan[]>([])
  const [products, setProducts] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [loading, setLoading] = useState(true)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [busy, setBusy] = useState(false)
  // Dialog fields.
  const [quantity, setQuantity] = useState('')
  const [additional, setAdditional] = useState(false)
  const [productId, setProductId] = useState('')
  const [requiredBy, setRequiredBy] = useState('')
  const [notes, setNotes] = useState('')
  const [reason, setReason] = useState('')
  const [schedulePlanId, setSchedulePlanId] = useState<number | null>(null)

  const load = useCallback(async () => {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ''))
    try {
      const [mrp, planList] = await Promise.all([
        apiClient.get<{ rows: MrpRow[]; material_summary: MaterialNeed[] }>('/api/mrp', { params }),
        apiClient.get<ProductionPlan[]>('/api/production-plans'),
      ])
      setRows(mrp.data.rows)
      setSummary(mrp.data.material_summary)
      setPlans(planList.data)
      setError(null)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setDenied(true)
      else setError(err instanceof ApiError ? err.message : 'Failed to load the production plan.')
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    Promise.all([
      apiClient.get<PaginatedResponse<LookupOption>>('/api/products', { params: { page_size: 200 } }),
      apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
    ])
      .then(([p, u]) => {
        setProducts(p.data.data)
        setUnits(u.data.data)
      })
      .catch(() => undefined)
  }, [])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u.code])), [units])
  const unit = (id: number) => unitsById.get(id) ?? ''

  function open(next: Dialog) {
    setActionError(null)
    setReason('')
    setNotes('')
    setRequiredBy('')
    setProductId('')
    setAdditional(false)
    if (next?.kind === 'customer') setQuantity(Number(next.row.proposed_quantity) > 0 ? String(Number(next.row.proposed_quantity)) : '')
    else if (next?.kind === 'edit') setQuantity(String(Number(next.plan.planned_quantity)))
    else setQuantity('')
    if (next?.kind === 'customer') setAdditional(next.row.plan_ids.length > 0)
    setDialog(next)
  }

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      setDialog(null)
      await load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  function submitDialog() {
    if (!dialog) return
    if (dialog.kind === 'customer') {
      act(() =>
        apiClient.post('/api/production-plans', {
          source_type: 'customer_demand',
          production_requirement_id: dialog.row.production_requirement_id,
          planned_quantity: quantity.trim() || null,
          additional,
          notes: notes.trim() || null,
        }),
      )
    } else if (dialog.kind === 'independent') {
      act(() =>
        apiClient.post('/api/production-plans', {
          source_type: 'independent',
          product_id: Number(productId),
          planned_quantity: quantity.trim(),
          required_by_date: requiredBy || null,
          notes: notes.trim() || null,
        }),
      )
    } else if (dialog.kind === 'edit') {
      act(() => apiClient.patch(`/api/production-plans/${dialog.plan.id}`, { planned_quantity: quantity.trim() }))
    } else if (dialog.kind === 'cancel') {
      act(() => apiClient.post(`/api/production-plans/${dialog.plan.id}/cancel`, { reason }))
    }
  }

  if (denied) return <AccessDeniedState message="Production planning needs the production view permission." />

  const setFilter = (key: keyof Filters) => (e: { target: { value: string } }) => setFilters((prev) => ({ ...prev, [key]: e.target.value }))

  const demandColumns: DataTableColumn<MrpRow>[] = [
    { key: 'product', label: 'Product', alwaysVisible: true, render: (r) => r.product_name },
    {
      key: 'source',
      label: 'Demand',
      render: (r) =>
        r.demand_type === 'independent' ? 'Independent' : `${r.sales_order_number ?? '—'}${r.line_number ? ` / line ${r.line_number}` : ''}`,
    },
    { key: 'required_by', label: 'Required By', hideBelow: 'sm', render: (r) => formatDate(r.required_by_date) },
    {
      key: 'outstanding',
      label: 'Outstanding Demand',
      align: 'right',
      render: (r) => (r.demand_type === 'independent' ? '—' : `${qty(r.outstanding_quantity)} ${unit(r.unit_of_measure_id)}`),
    },
    { key: 'free', label: 'Free FG', align: 'right', hideBelow: 'md', render: (r) => `${qty(r.fg_free)} ${unit(r.unit_of_measure_id)}` },
    {
      key: 'production',
      label: 'Planned / Proposed',
      align: 'right',
      render: (r) => `${qty(r.planned_quantity)} / ${qty(r.proposed_quantity)}${Number(r.excess_quantity) > 0 ? ` (+${qty(r.excess_quantity)} free)` : ''}`,
    },
    { key: 'bom', label: 'BOM', hideBelow: 'md', render: (r) => (r.bom_status === 'snapshot' ? 'Known' : 'BOM required') },
    {
      key: 'materials',
      label: 'Materials',
      hideBelow: 'md',
      render: (r) =>
        r.materials.length === 0 ? (
          '—'
        ) : (
          <Button variant="secondary" onClick={() => open({ kind: 'materials', row: r })}>
            {r.materials.some((m) => Number(m.shortage_quantity) > 0) ? 'Short' : 'Available'}
          </Button>
        ),
    },
    {
      key: 'exceptions',
      label: 'Exceptions',
      render: (r) => (
        <span className="flex flex-wrap gap-1">
          {r.exceptions.map((e) => (
            <Badge key={e} tone="danger">
              {EXCEPTION_LABELS[e] ?? e}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      key: 'plan_status',
      label: 'Plan',
      render: (r) => <Badge tone={PLAN_STATUS_TONES[r.plan_status] ?? 'neutral'}>{PLAN_STATUS_LABELS[r.plan_status] ?? r.plan_status}</Badge>,
    },
    {
      key: 'action',
      label: '',
      align: 'right',
      alwaysVisible: true,
      render: (r) =>
        r.demand_type === 'customer_demand' && r.requirement_status !== 'cancelled' && r.requirement_status !== 'satisfied' ? (
          <Button variant="secondary" onClick={() => open({ kind: 'customer', row: r })}>
            {r.plan_ids.length ? 'Add Plan' : 'Plan'}
          </Button>
        ) : null,
    },
  ]

  const planColumns: DataTableColumn<ProductionPlan>[] = [
    { key: 'id', label: 'Plan', alwaysVisible: true, render: (p) => `#${p.id}` },
    { key: 'product', label: 'Product', render: (p) => p.product_name ?? `Product ${p.product_id}` },
    { key: 'source', label: 'Source', render: (p) => (p.source_type === 'independent' ? 'Independent' : (p.sales_order_number ?? 'Customer demand')) },
    { key: 'required_by', label: 'Required By', hideBelow: 'sm', render: (p) => formatDate(p.required_by_date) },
    { key: 'quantity', label: 'Quantity', align: 'right', render: (p) => `${qty(p.planned_quantity)} ${unit(p.unit_of_measure_id)}` },
    {
      key: 'status',
      label: 'Status',
      render: (p) => (
        <span title={p.cancellation_reason ?? undefined}>
          <Badge tone={PLAN_STATUS_TONES[p.status] ?? 'neutral'}>{PLAN_STATUS_LABELS[p.status] ?? p.status}</Badge>
        </span>
      ),
    },
    {
      key: 'actions',
      label: '',
      align: 'right',
      alwaysVisible: true,
      render: (p) =>
        p.status === 'cancelled' ? null : (
          <span className="flex justify-end gap-2">
            {p.status === 'draft' && (
              <>
                <Button variant="secondary" onClick={() => open({ kind: 'edit', plan: p })}>Edit</Button>
                <Button variant="secondary" onClick={() => act(() => apiClient.post(`/api/production-plans/${p.id}/plan`))} disabled={busy}>
                  Accept Plan
                </Button>
              </>
            )}
            {p.status === 'planned' && (
              <Button variant="secondary" onClick={() => setSchedulePlanId(p.id)}>Schedule</Button>
            )}
            <Button variant="danger" onClick={() => open({ kind: 'cancel', plan: p })}>Cancel</Button>
          </span>
        ),
    },
  ]

  const dialogTitle =
    dialog?.kind === 'customer'
      ? `Plan production: ${dialog.row.product_name} (${dialog.row.sales_order_number})`
      : dialog?.kind === 'independent'
        ? 'New independent production plan'
        : dialog?.kind === 'edit'
          ? `Edit plan #${dialog.plan.id}`
          : dialog?.kind === 'cancel'
            ? `Cancel plan #${dialog.plan.id}`
            : dialog?.kind === 'materials'
              ? `Raw materials: ${dialog.row.product_name}`
              : ''

  return (
    <div className="space-y-6">
      <PageHeader
        title="Production Planning"
        subtitle="What needs to be produced, how much, and why. Plans are decisions -- nothing here produces, schedules or moves stock."
        actions={<Button onClick={() => open({ kind: 'independent' })}>New Independent Plan</Button>}
      />
      <Alert variant="danger">{error}</Alert>
      {!dialog && <Alert variant="danger">{actionError}</Alert>}

      <Card className="space-y-3 p-4 sm:p-6">
        <FormSectionHeading>Demand</FormSectionHeading>
        <FilterBar>
          <DateField label="Required from" value={filters.required_by_from} onChange={setFilter('required_by_from')} />
          <DateField label="Required to" value={filters.required_by_to} onChange={setFilter('required_by_to')} />
          <SelectField label="Product" value={filters.product_id} onChange={setFilter('product_id')}>
            <option value="">All</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Demand type" value={filters.demand_type} onChange={setFilter('demand_type')}>
            <option value="">All</option>
            <option value="customer_demand">Customer demand</option>
            <option value="independent">Independent</option>
          </SelectField>
          <SelectField label="Plan status" value={filters.plan_status} onChange={setFilter('plan_status')}>
            <option value="">All</option>
            {['unplanned', 'partially_planned', 'draft', 'planned'].map((s) => (
              <option key={s} value={s}>
                {PLAN_STATUS_LABELS[s]}
              </option>
            ))}
          </SelectField>
          <SelectField label="Exception" value={filters.exception} onChange={setFilter('exception')}>
            <option value="">All</option>
            <option value="any">Any exception</option>
            <option value="bom_required">BOM required</option>
            <option value="material_shortage">Material shortage</option>
          </SelectField>
        </FilterBar>
        <DataTable
          columns={demandColumns}
          rows={rows}
          rowKey={(r) => (r.production_requirement_id !== null ? `r${r.production_requirement_id}` : `p${r.plan_ids[0]}`)}
          loading={loading}
          emptyTitle="Nothing to produce"
          emptyMessage="Uncovered customer demand and independent plans appear here."
        />
      </Card>

      {summary.length > 0 && (
        <Card className="space-y-3 p-4 sm:p-6">
          <FormSectionHeading>Raw materials across all demand shown</FormSectionHeading>
          <MaterialTable needs={summary} />
        </Card>
      )}

      <Card className="space-y-3 p-4 sm:p-6">
        <FormSectionHeading>Production Plans</FormSectionHeading>
        <DataTable columns={planColumns} rows={plans} rowKey={(p) => p.id} loading={loading} emptyTitle="No plans yet" emptyMessage="Plan from the demand above, or add independent production." />
      </Card>

      <PlanScheduleDialog planId={schedulePlanId} onClose={() => setSchedulePlanId(null)} />
      <Modal
        open={dialog !== null}
        title={dialogTitle}
        onClose={() => setDialog(null)}
        size={dialog?.kind === 'materials' ? 'wide' : 'default'}
        footer={
          dialog?.kind === 'materials' ? (
            <Button variant="secondary" onClick={() => setDialog(null)}>Close</Button>
          ) : (
            <>
              <Button variant="secondary" onClick={() => setDialog(null)} disabled={busy}>Back</Button>
              <Button
                variant={dialog?.kind === 'cancel' ? 'danger' : 'primary'}
                onClick={submitDialog}
                isLoading={busy}
                disabled={
                  busy ||
                  (dialog?.kind === 'cancel' && !reason.trim()) ||
                  (dialog?.kind === 'independent' && (!productId || !quantity.trim())) ||
                  (dialog?.kind === 'edit' && !quantity.trim())
                }
              >
                {dialog?.kind === 'cancel' ? 'Cancel Plan' : 'Save'}
              </Button>
            </>
          )
        }
      >
        <div className="space-y-3">
          <Alert variant="danger">{actionError}</Alert>
          {dialog?.kind === 'customer' && (
            <>
              <p className="text-sm text-gold-100/70">
                Outstanding demand {qty(dialog.row.outstanding_quantity)}, already planned {qty(dialog.row.planned_quantity)}. You may plan more than
                the demand; the excess stays free stock and is not assigned to the customer.
              </p>
              <TextField label="Quantity to plan" type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
              {dialog.row.plan_ids.length > 0 && (
                <CheckboxField
                  label="This demand already has a plan: create an additional plan on purpose."
                  checked={additional}
                  onChange={(e) => setAdditional(e.target.checked)}
                />
              )}
              <TextareaField label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </>
          )}
          {dialog?.kind === 'independent' && (
            <>
              <SelectField label="Product" required value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">Choose…</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </SelectField>
              <TextField label="Quantity (product's unit)" required type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
              <DateField label="Required by (optional)" value={requiredBy} onChange={(e) => setRequiredBy(e.target.value)} />
              <TextareaField label="Why (e.g. build stock)" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </>
          )}
          {dialog?.kind === 'edit' && (
            <TextField label="Planned quantity" type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          )}
          {dialog?.kind === 'cancel' && <TextareaField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />}
          {dialog?.kind === 'materials' && <MaterialTable needs={dialog.row.materials} />}
        </div>
      </Modal>
    </div>
  )
}

function MaterialTable({ needs }: { needs: MaterialNeed[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
            <th className="py-2 pr-3">Raw material</th>
            <th className="py-2 pr-3 text-right">Required</th>
            <th className="py-2 pr-3 text-right">On hand</th>
            <th className="py-2 pr-3 text-right">Committed</th>
            <th className="py-2 pr-3 text-right">Available</th>
            <th className="py-2 text-right">Shortage</th>
          </tr>
        </thead>
        <tbody>
          {needs.map((m) => (
            <tr key={m.raw_material_id} className="border-t border-ink-700">
              <td className="py-2 pr-3">{m.raw_material_name}</td>
              <td className="py-2 pr-3 text-right">{m.unit_mismatch ? 'Unit mismatch' : `${qty(m.required_quantity)} ${m.unit_code ?? ''}`}</td>
              <td className="py-2 pr-3 text-right">{qty(m.on_hand_quantity)}</td>
              <td className="py-2 pr-3 text-right">{qty(m.committed_quantity)}</td>
              <td className="py-2 pr-3 text-right">{qty(m.available_quantity)}</td>
              <td className={`py-2 text-right ${Number(m.shortage_quantity) > 0 ? 'text-red-400' : ''}`}>{qty(m.shortage_quantity)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
