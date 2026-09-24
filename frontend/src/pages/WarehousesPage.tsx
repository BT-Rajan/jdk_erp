import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { ActionMenu, type ActionMenuOption } from '@/components/ui/ActionMenu'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { FilterBar } from '@/components/ui/FilterBar'
import { FormPage } from '@/components/ui/FormPage'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import { useFormRoute } from '@/lib/useFormRoute'

/** Mirrors backend/app/schemas/warehouse.py's WarehouseOut. */
interface Warehouse {
  id: number
  organisation_id: number
  code: string
  name: string
  total_usable_storage_area: string
  storage_area_unit_of_measure_id: number
  is_active: boolean
}

interface LookupOption {
  id: number
  name: string
  code: string | null
  is_active: boolean
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface WarehousesFilters {
  search: string
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

const warehouseSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  total_usable_storage_area: z
    .string()
    .min(1, 'Storage area is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
  storage_area_unit_of_measure_id: z.string().min(1, 'Storage area unit is required'),
})

type WarehouseFormValues = z.infer<typeof warehouseSchema>

const emptyDefaults: WarehouseFormValues = {
  name: '',
  total_usable_storage_area: '',
  storage_area_unit_of_measure_id: '',
}

function toFormValues(warehouse: Warehouse): WarehouseFormValues {
  return {
    name: warehouse.name,
    total_usable_storage_area: warehouse.total_usable_storage_area,
    storage_area_unit_of_measure_id: String(warehouse.storage_area_unit_of_measure_id),
  }
}

async function fetchWarehouses({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: WarehousesFilters
}): Promise<ServerTableResult<Warehouse>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  const { data } = await apiClient.get<PaginatedResponse<Warehouse>>('/api/warehouses', {
    params: {
      page,
      page_size: pageSize,
      sort_by: sort?.field,
      sort_direction: sort?.direction,
      include_inactive: true,
      q: filters.search || undefined,
    },
  })
  return { rows: data.data, total: data.pagination.total }
}

/** The authoritative physical storage location inside the JDK factory
 * and its configured total storage capacity
 * (backend/app/api/warehouses.py, docs/modules/warehouses.md). A
 * configuration-level master, not an operational dashboard -- composed
 * identically to MachinesPage: a Storage Area Unit dropdown reuses
 * GET /api/units-of-measure, the same pattern Machine's Capacity Unit
 * dropdown already established. No stock/utilisation summaries are
 * shown -- Inventory doesn't exist yet to source them from
 * (docs/modules/warehouses.md #22). `code` is system-generated and
 * immutable -- there is no Code input on Create; the Edit dialog shows
 * it disabled purely for reference. */
export function WarehousesPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [editingWarehouse, setEditingWarehouse] = useState<Warehouse | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Warehouse | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<WarehouseFormValues>({ resolver: zodResolver(warehouseSchema), defaultValues: emptyDefaults })

  const table = useServerTable<Warehouse, WarehousesFilters>({
    fetcher: fetchWarehouses,
    pageSize: 20,
    initialFilters: { search: '' },
  })

  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  const loadLookups = useCallback(async () => {
    try {
      const { data } = await apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', {
        params: { page_size: 200 },
      })
      setUnits(data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load units of measure.')
    }
  }, [])

  useEffect(() => {
    if (canManage) void loadLookups()
  }, [canManage, loadLookups])

  function prepareCreate() {
    setEditingWarehouse(null)
    reset(emptyDefaults)
    setFormError(null)
  }

  function prepareEdit(warehouse: Warehouse) {
    setEditingWarehouse(warehouse)
    reset(toFormValues(warehouse))
    setFormError(null)
  }

  const { formOpen, loading: formLoading, loadError: formLoadError, openCreate, openEdit, closeForm } = useFormRoute<Warehouse>(
    '/warehouses',
    '/api/warehouses',
    { onCreate: prepareCreate, onEdit: prepareEdit },
  )

  const onFormSubmit = useCallback(
    async (values: WarehouseFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        total_usable_storage_area: values.total_usable_storage_area,
        storage_area_unit_of_measure_id: Number(values.storage_area_unit_of_measure_id),
      }
      try {
        if (editingWarehouse) {
          await apiClient.patch(`/api/warehouses/${editingWarehouse.id}`, payload)
        } else {
          await apiClient.post('/api/warehouses', payload)
        }
        closeForm()
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof WarehouseFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingWarehouse, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/warehouses/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<Warehouse>[] = [
    { key: 'code', label: 'Code', sortable: true, render: (w) => w.code },
    { key: 'name', label: 'Warehouse', sortable: true, render: (w) => w.name },
    {
      key: 'capacity',
      label: 'Total Usable Storage Area',
      hideBelow: 'sm',
      render: (w) => `${w.total_usable_storage_area} ${unitsById.get(w.storage_area_unit_of_measure_id)?.code ?? '?'}`,
    },
    {
      key: 'status',
      label: 'Status',
      render: (w) => <Badge tone={w.is_active ? 'success' : 'danger'}>{w.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (w: Warehouse) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(w) },
                w.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(w) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(w) },
              ]
              return <ActionMenu label={`Actions for ${w.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <div hidden={formOpen} className="space-y-6">
        <PageHeader
          title="Warehouses"
          subtitle="The physical storage location inside the factory and its configured storage capacity."
          actions={canManage ? <Button onClick={openCreate}>New Warehouse</Button> : undefined}
        />

        <Alert variant="danger">{pageError}</Alert>

        <FilterBar>
          <TextField
            label="Search"
            placeholder="Search by name or code..."
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </FilterBar>

        <DataTable
          columns={columns}
          rows={table.rows}
          rowKey={(w) => w.id}
          loading={table.loading}
          error={table.error}
          sort={table.sort}
          onSortChange={table.setSort}
          page={table.page}
          totalPages={table.totalPages}
          total={table.total}
          onPageChange={table.setPage}
          pageSize={table.pageSize}
          onPageSizeChange={table.setPageSize}
          emptyTitle={debouncedSearch ? 'No matching warehouses' : 'No warehouses yet'}
          emptyMessage={
            debouncedSearch
              ? 'Try a different search term.'
              : canManage
                ? 'Create the first warehouse with the New Warehouse button above.'
                : 'No warehouses have been created yet.'
          }
        />
      </div>

      {canManage && (
        <>
          <FormPage
            loading={formLoading}
            loadError={formLoadError}
            open={formOpen}
            title={editingWarehouse ? 'Edit Warehouse' : 'New Warehouse'}
            onClose={closeForm}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingWarehouse ? 'Save' : 'Create warehouse'}
          >
            <Alert variant="danger">{formError}</Alert>
            {editingWarehouse && (
              <TextField label="Code" disabled readOnly hint="System-generated. Cannot be changed." value={editingWarehouse.code} />
            )}
            <TextField label="Name" required {...register('name')} error={errors.name?.message} />
            <TextField
              label="Total Usable Storage Area"
              required
              hint="Total configured capacity -- not a live occupied/available calculation."
              {...register('total_usable_storage_area')}
              error={errors.total_usable_storage_area?.message}
            />
            <SelectField
              label="Storage Area Unit"
              required
              {...register('storage_area_unit_of_measure_id')}
              error={errors.storage_area_unit_of_measure_id?.message}
            >
              <option value="">Select a unit of measure...</option>
              {units
                .filter((u) => u.is_active)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.code})
                  </option>
                ))}
            </SelectField>
          </FormPage>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate warehouse' : 'Activate warehouse'}
            message={
              statusTarget?.is_active
                ? `${statusTarget.name} will no longer be selectable for new inventory operations. Existing records that reference it are unaffected.`
                : `${statusTarget?.name ?? ''} will be selectable for new inventory operations again.`
            }
            confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
            danger={statusTarget?.is_active}
            busy={statusBusy}
            onConfirm={confirmStatusChange}
            onCancel={() => setStatusTarget(null)}
          />
        </>
      )}
    </div>
  )
}
