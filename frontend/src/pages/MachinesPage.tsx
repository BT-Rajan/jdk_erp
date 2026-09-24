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

/** Mirrors backend/app/schemas/machine.py's MachineOut. */
interface Machine {
  id: number
  organisation_id: number
  code: string
  name: string
  production_line_id: number
  capacity_quantity: string
  capacity_unit_of_measure_id: number
  capacity_period_hours: string
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

interface MachinesFilters {
  search: string
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

const machineSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  production_line_id: z.string().min(1, 'Production line is required'),
  capacity_quantity: z
    .string()
    .min(1, 'Capacity is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
  capacity_unit_of_measure_id: z.string().min(1, 'Capacity unit is required'),
  capacity_period_hours: z
    .string()
    .min(1, 'Period is required')
    .refine((v) => DECIMAL_RE.test(v) && Number(v) > 0, 'Enter a positive number'),
})

type MachineFormValues = z.infer<typeof machineSchema>

const emptyDefaults: MachineFormValues = {
  name: '',
  production_line_id: '',
  capacity_quantity: '',
  capacity_unit_of_measure_id: '',
  capacity_period_hours: '1',
}

function toFormValues(machine: Machine): MachineFormValues {
  return {
    name: machine.name,
    production_line_id: String(machine.production_line_id),
    capacity_quantity: machine.capacity_quantity,
    capacity_unit_of_measure_id: String(machine.capacity_unit_of_measure_id),
    capacity_period_hours: machine.capacity_period_hours,
  }
}

async function fetchMachines({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: MachinesFilters
}): Promise<ServerTableResult<Machine>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  const { data } = await apiClient.get<PaginatedResponse<Machine>>('/api/machines', {
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

function formatCapacity(machine: Machine, unitCode: string | undefined) {
  const unit = unitCode ?? '?'
  const period = Number(machine.capacity_period_hours)
  const periodLabel = period === 1 ? 'hour' : `${machine.capacity_period_hours} hours`
  return `${machine.capacity_quantity} ${unit} / ${periodLabel}`
}

/** The authoritative physical production resource and its configured
 * production rate (backend/app/api/machines.py, docs/modules/machines.md).
 * Composed identically to ProductsPage -- a Production Line dropdown
 * (reusing GET /api/production-lines) plays the same role Product's
 * Category dropdown does, and Capacity Unit reuses GET
 * /api/units-of-measure exactly like Product/RawMaterial. Capacity is
 * three structured fields (quantity/unit/period), never a free-text
 * string -- the whole point of this master (docs/modules/machines.md
 * #4). `code` is system-generated and immutable -- there is no Code
 * input on Create; the Edit dialog shows it disabled purely for
 * reference. */
export function MachinesPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [productionLines, setProductionLines] = useState<LookupOption[]>([])
  const [units, setUnits] = useState<LookupOption[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [editingMachine, setEditingMachine] = useState<Machine | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Machine | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<MachineFormValues>({ resolver: zodResolver(machineSchema), defaultValues: emptyDefaults })

  const table = useServerTable<Machine, MachinesFilters>({
    fetcher: fetchMachines,
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

  const linesById = useMemo(() => new Map(productionLines.map((l) => [l.id, l])), [productionLines])
  const unitsById = useMemo(() => new Map(units.map((u) => [u.id, u])), [units])

  const loadLookups = useCallback(async () => {
    try {
      const [linesResponse, unitsResponse] = await Promise.all([
        apiClient.get<PaginatedResponse<LookupOption>>('/api/production-lines', { params: { page_size: 200 } }),
        apiClient.get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } }),
      ])
      setProductionLines(linesResponse.data.data)
      setUnits(unitsResponse.data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load production lines and units of measure.')
    }
  }, [])

  useEffect(() => {
    if (canManage) void loadLookups()
  }, [canManage, loadLookups])

  function prepareCreate() {
    setEditingMachine(null)
    reset(emptyDefaults)
    setFormError(null)
  }

  function prepareEdit(machine: Machine) {
    setEditingMachine(machine)
    reset(toFormValues(machine))
    setFormError(null)
  }

  const { formOpen, loading: formLoading, loadError: formLoadError, openCreate, openEdit, closeForm } = useFormRoute<Machine>(
    '/machines',
    '/api/machines',
    { onCreate: prepareCreate, onEdit: prepareEdit },
  )

  const onFormSubmit = useCallback(
    async (values: MachineFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        production_line_id: Number(values.production_line_id),
        capacity_quantity: values.capacity_quantity,
        capacity_unit_of_measure_id: Number(values.capacity_unit_of_measure_id),
        capacity_period_hours: values.capacity_period_hours,
      }
      try {
        if (editingMachine) {
          await apiClient.patch(`/api/machines/${editingMachine.id}`, payload)
        } else {
          await apiClient.post('/api/machines', payload)
        }
        closeForm()
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof MachineFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingMachine, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/machines/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<Machine>[] = [
    { key: 'code', label: 'Code', sortable: true, render: (m) => m.code },
    { key: 'name', label: 'Machine', sortable: true, render: (m) => m.name },
    {
      key: 'line',
      label: 'Production Line',
      hideBelow: 'md',
      render: (m) => linesById.get(m.production_line_id)?.name ?? <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'capacity',
      label: 'Capacity',
      hideBelow: 'sm',
      render: (m) => formatCapacity(m, unitsById.get(m.capacity_unit_of_measure_id)?.code ?? undefined),
    },
    {
      key: 'status',
      label: 'Status',
      render: (m) => <Badge tone={m.is_active ? 'success' : 'danger'}>{m.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (m: Machine) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(m) },
                m.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(m) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(m) },
              ]
              return <ActionMenu label={`Actions for ${m.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <div hidden={formOpen} className="space-y-6">
        <PageHeader
          title="Machines"
          subtitle="The physical production resource and its configured production rate."
          actions={canManage ? <Button onClick={openCreate}>New Machine</Button> : undefined}
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
          rowKey={(m) => m.id}
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
          emptyTitle={debouncedSearch ? 'No matching machines' : 'No machines yet'}
          emptyMessage={
            debouncedSearch
              ? 'Try a different search term.'
              : canManage
                ? 'Create the first machine with the New Machine button above.'
                : 'No machines have been created yet.'
          }
        />
      </div>

      {canManage && (
        <>
          <FormPage
            loading={formLoading}
            loadError={formLoadError}
            open={formOpen}
            title={editingMachine ? 'Edit Machine' : 'New Machine'}
            onClose={closeForm}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingMachine ? 'Save' : 'Create machine'}
          >
            <Alert variant="danger">{formError}</Alert>
            {editingMachine && (
              <TextField label="Code" disabled readOnly hint="System-generated. Cannot be changed." value={editingMachine.code} />
            )}
            <TextField label="Name" required {...register('name')} error={errors.name?.message} />
            <SelectField
              label="Production Line"
              required
              {...register('production_line_id')}
              error={errors.production_line_id?.message}
            >
              <option value="">Select a production line...</option>
              {productionLines
                .filter((l) => l.is_active)
                .map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
            </SelectField>
            <TextField
              label="Production Capacity"
              required
              hint="The quantity produced per configured period, e.g. 2."
              {...register('capacity_quantity')}
              error={errors.capacity_quantity?.message}
            />
            <SelectField
              label="Capacity Unit"
              required
              {...register('capacity_unit_of_measure_id')}
              error={errors.capacity_unit_of_measure_id?.message}
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
            <TextField
              label="Capacity Period (hours)"
              required
              hint="e.g. 1 for '2 tonnes per hour'."
              {...register('capacity_period_hours')}
              error={errors.capacity_period_hours?.message}
            />
          </FormPage>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate machine' : 'Activate machine'}
            message={
              statusTarget?.is_active
                ? `${statusTarget.name} will no longer be selectable for new production scheduling. Existing records that reference it are unaffected.`
                : `${statusTarget?.name ?? ''} will be selectable for new production scheduling again.`
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
