import { useCallback, useEffect, useRef, useState } from 'react'
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
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import { useFormRoute } from '@/lib/useFormRoute'

/** Mirrors backend/app/schemas/unit.py's UnitOfMeasureOut. `dimension`/
 * `conversion_factor_to_base` are the universal-conversion half of BOM's
 * two conversion mechanisms (docs/modules/boms.md #3) -- both null, or
 * both set. */
interface UnitOfMeasure {
  id: number
  organisation_id: number
  name: string
  code: string
  description: string | null
  dimension: string | null
  conversion_factor_to_base: string | null
  is_active: boolean
}

/** Mirrors backend/app/schemas/pagination.py's PaginatedResponse. */
interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface UnitsFilters {
  search: string
}

const DECIMAL_RE = /^\d+(\.\d{1,6})?$/

const unitSchema = z
  .object({
    name: z.string().min(1, 'Name is required'),
    code: z.string().min(1, 'Code is required'),
    description: z.string(),
    dimension: z.string(),
    conversion_factor_to_base: z.string().refine((v) => v === '' || DECIMAL_RE.test(v), 'Enter a valid factor'),
  })
  // Both-or-neither, same discipline as the backend (docs/modules/boms.md #3).
  .refine((data) => (data.dimension.trim() === '') === (data.conversion_factor_to_base.trim() === ''), {
    message: 'Dimension and conversion factor must be provided together, or both left blank.',
    path: ['conversion_factor_to_base'],
  })

type UnitFormValues = z.infer<typeof unitSchema>

const emptyDefaults: UnitFormValues = {
  name: '',
  code: '',
  description: '',
  dimension: '',
  conversion_factor_to_base: '',
}

function toFormValues(unit: UnitOfMeasure): UnitFormValues {
  return {
    name: unit.name,
    code: unit.code,
    description: unit.description ?? '',
    dimension: unit.dimension ?? '',
    conversion_factor_to_base: unit.conversion_factor_to_base ?? '',
  }
}

async function fetchUnits({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: UnitsFilters
}): Promise<ServerTableResult<UnitOfMeasure>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md):
  // page/page_size/sort_by/sort_direction/q, all applied server-side to
  // the same organisation-scoped query.
  const { data } = await apiClient.get<PaginatedResponse<UnitOfMeasure>>('/api/units-of-measure', {
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

/** The single authoritative unit definition used for quantities across
 * JDK (backend/app/api/units.py, docs/modules/units_of_measure.md).
 * Deliberately has no conversion mechanism -- jdk_clean tried one
 * (a factor-to-base column), removed it within a week for conflating a
 * true physical ratio with a business-specific packaging assumption in
 * one field, and never rebuilt it (see docs/audit/UNITS_OF_MEASURE_AUDIT.md).
 * Composed exactly like CategoriesPage: read is open to any authenticated
 * organisation member, only create/edit/activate-deactivate are
 * admin-gated. Server-side is the real boundary (Principle 3); hiding
 * the mutating controls for a non-admin here is a usability courtesy. */
export function UnitsOfMeasurePage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [editingUnit, setEditingUnit] = useState<UnitOfMeasure | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<UnitOfMeasure | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<UnitFormValues>({ resolver: zodResolver(unitSchema), defaultValues: emptyDefaults })

  const table = useServerTable<UnitOfMeasure, UnitsFilters>({
    fetcher: fetchUnits,
    pageSize: 20,
    initialFilters: { search: '' },
  })

  // Debounced search feeding into the table's own filter state -- see
  // UsersPage.tsx for why the first render is skipped (useServerTable
  // already fetches once on mount with initialFilters).
  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
  }, [debouncedSearch])

  function prepareCreate() {
    setEditingUnit(null)
    reset(emptyDefaults)
    setFormError(null)
  }

  function prepareEdit(unit: UnitOfMeasure) {
    setEditingUnit(unit)
    reset(toFormValues(unit))
    setFormError(null)
  }

  const { formOpen, loading: formLoading, loadError: formLoadError, openCreate, openEdit, closeForm } = useFormRoute<UnitOfMeasure>(
    '/units-of-measure',
    '/api/units-of-measure',
    { onCreate: prepareCreate, onEdit: prepareEdit },
  )

  const onFormSubmit = useCallback(
    async (values: UnitFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        code: values.code,
        description: values.description || null,
        dimension: values.dimension || null,
        conversion_factor_to_base: values.conversion_factor_to_base || null,
      }
      try {
        if (editingUnit) {
          await apiClient.patch(`/api/units-of-measure/${editingUnit.id}`, payload)
        } else {
          await apiClient.post('/api/units-of-measure', payload)
        }
        closeForm()
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof UnitFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingUnit, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/units-of-measure/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<UnitOfMeasure>[] = [
    { key: 'name', label: 'Name', sortable: true, render: (u) => u.name },
    { key: 'code', label: 'Symbol', sortable: true, hideBelow: 'sm', render: (u) => u.code },
    {
      key: 'description',
      label: 'Description',
      hideBelow: 'md',
      render: (u) => u.description ?? <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'dimension',
      label: 'Dimension',
      hideBelow: 'lg',
      render: (u) => u.dimension ?? <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'status',
      label: 'Status',
      render: (u) => <Badge tone={u.is_active ? 'success' : 'danger'}>{u.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (u: UnitOfMeasure) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(u) },
                u.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(u) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(u) },
              ]
              return <ActionMenu label={`Actions for ${u.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <div hidden={formOpen} className="space-y-6">
        <PageHeader
          title="Units of Measure"
          subtitle="The unit definitions used to express quantities for Products and Raw Materials."
          actions={canManage ? <Button onClick={openCreate}>New Unit</Button> : undefined}
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
          rowKey={(u) => u.id}
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
          emptyTitle={debouncedSearch ? 'No matching units' : 'No units yet'}
          emptyMessage={
            debouncedSearch
              ? 'Try a different search term.'
              : canManage
                ? 'Create the first unit with the New Unit button above.'
                : 'No units have been created yet.'
          }
        />
      </div>

      {canManage && (
        <>
          <FormPage
            loading={formLoading}
            loadError={formLoadError}
            open={formOpen}
            title={editingUnit ? 'Edit Unit' : 'New Unit'}
            onClose={closeForm}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingUnit ? 'Save' : 'Create unit'}
          >
            <Alert variant="danger">{formError}</Alert>
            <TextField label="Name" required {...register('name')} error={errors.name?.message} />
            <TextField
              label="Symbol"
              hint="Short abbreviation, e.g. KG. Stored upper-case. Unlike other masters' auto-generated Code, this is a meaningful symbol you choose."
              required
              {...register('code')}
              error={errors.code?.message}
            />
            <TextareaField label="Description" {...register('description')} error={errors.description?.message} />
            <TextField
              label="Dimension"
              hint='Optional. A universal conversion family, e.g. "mass" or "volume" -- leave both this and Conversion Factor blank if this unit does not convert (e.g. "pcs").'
              {...register('dimension')}
              error={errors.dimension?.message}
            />
            <TextField
              label="Conversion Factor to Base"
              hint="Optional. This unit's ratio within its Dimension, e.g. Tonne = 1000 when Kilogram = 1. Must be set together with Dimension."
              {...register('conversion_factor_to_base')}
              error={errors.conversion_factor_to_base?.message}
            />
          </FormPage>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate unit' : 'Activate unit'}
            message={
              statusTarget?.is_active
                ? `${statusTarget.name} will no longer be selectable for new records. Existing records that reference it are unaffected.`
                : `${statusTarget?.name ?? ''} will be selectable for new records again.`
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
