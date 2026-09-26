import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { PageHeader } from '@/components/ui/PageHeader'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import type { LookupOption, PaginatedResponse } from './rfqShared'

/** Mirrors backend/app/schemas/production_requirement.py's ProductionRequirementRowOut. */
export interface ProductionRequirementRow {
  id: number
  sales_order_id: number
  sales_order_number: string | null
  sales_order_status: string | null
  customer_name: string | null
  line_number: number | null
  product_id: number
  product_name: string | null
  unit_of_measure_id: number
  ordered_quantity: string | null
  covered_quantity: string | null
  quantity: string
  delivered_quantity: string
  required_quantity: string
  allocated_quantity: string
  outstanding_quantity: string
  required_by_date: string | null
  status: string
  bom_id: number | null
  cancellation_reason: string | null
  can_resolve_bom: boolean
}

const STATUS_LABELS: Record<string, string> = {
  bom_required: 'BOM required',
  open: 'Open',
  satisfied: 'Satisfied',
  cancelled: 'Cancelled',
}
const STATUS_TONES: Record<string, BadgeTone> = {
  bom_required: 'warning',
  open: 'info',
  satisfied: 'success',
  cancelled: 'neutral',
}

interface Filters {
  status: string
  search: string
}

const qty = (value: string | null) => (value === null ? '—' : formatNumber(value, { maximumFractionDigits: 4 }))

/** Production -> Requirements (backend/app/api/production_requirements.py):
 * read-only customer demand/shortfall recorded at Sales hand-off -- not
 * production instructions. Needs production:view; the one action, taking
 * the BOM snapshot of a `bom_required` requirement, is offered only when
 * the server says so (production:manage). */
export function ProductionRequirementsPage() {
  const [denied, setDenied] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [units, setUnits] = useState<LookupOption[]>([])
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const fetchRows = useCallback(
    async ({ page, pageSize, filters }: { page: number; pageSize: number; filters: Filters }): Promise<ServerTableResult<ProductionRequirementRow>> => {
      const { data } = await apiClient
        .get<PaginatedResponse<ProductionRequirementRow>>('/api/production-requirements', {
          params: { page, page_size: pageSize, status: filters.status || undefined, q: filters.search || undefined },
        })
        .catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 403) setDenied(true)
          throw err
        })
      return { rows: data.data, total: data.pagination.total }
    },
    [],
  )
  const table = useServerTable<ProductionRequirementRow, Filters>({ fetcher: fetchRows, pageSize: 20, initialFilters: { status: '', search: '' } })

  useEffect(() => {
    apiClient
      .get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } })
      .then((res) => setUnits(res.data.data))
      .catch(() => undefined)
  }, [])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  const isFirstSearch = useRef(true)
  useEffect(() => {
    if (isFirstSearch.current) {
      isFirstSearch.current = false
      return
    }
    table.setFilters({ ...table.filters, search: debouncedSearch })
  }, [debouncedSearch])

  async function resolveBom(row: ProductionRequirementRow) {
    setBusyId(row.id)
    setActionError(null)
    try {
      await apiClient.post(`/api/production-requirements/${row.id}/snapshot-bom`)
      table.refetch()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusyId(null)
    }
  }

  if (denied) return <AccessDeniedState message="Production requirements need the production view permission." />

  const unit = (row: ProductionRequirementRow) => unitsById.get(row.unit_of_measure_id)?.code ?? ''
  const columns: DataTableColumn<ProductionRequirementRow>[] = [
    {
      key: 'source',
      label: 'Sales Order',
      alwaysVisible: true,
      render: (r) => `${r.sales_order_number ?? '—'}${r.line_number ? ` / line ${r.line_number}` : ''}`,
    },
    { key: 'customer', label: 'Customer', hideBelow: 'lg', render: (r) => r.customer_name ?? '—' },
    { key: 'product', label: 'Product', render: (r) => r.product_name ?? `Product ${r.product_id}` },
    { key: 'required', label: 'Required', align: 'right', hideBelow: 'md', render: (r) => `${qty(r.required_quantity)} ${unit(r)}` },
    { key: 'allocated', label: 'Allocated FG', align: 'right', hideBelow: 'md', render: (r) => `${qty(r.allocated_quantity)} ${unit(r)}` },
    { key: 'outstanding', label: 'To Produce', align: 'right', render: (r) => `${qty(r.outstanding_quantity)} ${unit(r)}` },
    { key: 'required_by', label: 'Required By', hideBelow: 'sm', render: (r) => formatDate(r.required_by_date) },
    { key: 'bom', label: 'BOM', hideBelow: 'sm', render: (r) => (r.bom_id ? 'Snapshot taken' : 'None') },
    {
      key: 'status',
      label: 'Status',
      alwaysVisible: true,
      render: (r) => (
        <span title={r.cancellation_reason ?? undefined}>
          <Badge tone={STATUS_TONES[r.status] ?? 'neutral'}>{STATUS_LABELS[r.status] ?? r.status}</Badge>
        </span>
      ),
    },
    {
      key: 'action',
      label: '',
      align: 'right',
      alwaysVisible: true,
      render: (r) =>
        r.can_resolve_bom ? (
          <Button variant="secondary" onClick={() => resolveBom(r)} isLoading={busyId === r.id} disabled={busyId !== null}>
            Take BOM Snapshot
          </Button>
        ) : null,
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Production Requirements"
        subtitle="Customer demand not covered by delivered or allocated FG. Demand to be aware of -- not an instruction to produce an exact quantity."
      />
      <Alert variant="danger">{actionError}</Alert>
      <Card className="space-y-3 p-4 sm:p-6">
        <FilterBar>
          <SelectField label="Status" value={table.filters.status} onChange={(e) => table.setFilters({ ...table.filters, status: e.target.value })}>
            <option value="">All</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectField>
          <TextField label="Search" placeholder="Sales Order or product..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        </FilterBar>
        <DataTable
          columns={columns}
          rows={table.rows}
          rowKey={(r) => r.id}
          loading={table.loading}
          error={table.error}
          page={table.page}
          totalPages={table.totalPages}
          total={table.total}
          onPageChange={table.setPage}
          pageSize={table.pageSize}
          onPageSizeChange={table.setPageSize}
          emptyTitle="No production requirements"
          emptyMessage="Shortfalls of handed-off Sales Orders appear here."
        />
      </Card>
    </div>
  )
}
