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
import { FormDialog } from '@/components/ui/FormDialog'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/production_line.py's ProductionLineOut. */
interface ProductionLine {
  id: number
  organisation_id: number
  code: string
  name: string
  is_active: boolean
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface ProductionLinesFilters {
  search: string
}

const lineSchema = z.object({
  name: z.string().min(1, 'Name is required'),
})

type LineFormValues = z.infer<typeof lineSchema>

const emptyDefaults: LineFormValues = { name: '' }

function toFormValues(line: ProductionLine): LineFormValues {
  return { name: line.name }
}

async function fetchProductionLines({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: ProductionLinesFilters
}): Promise<ServerTableResult<ProductionLine>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  const { data } = await apiClient.get<PaginatedResponse<ProductionLine>>('/api/production-lines', {
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

/** The production flow/resource a Machine runs on
 * (backend/app/api/production_lines.py, docs/modules/machines.md).
 * Deliberately kept a genuinely separate master from Machine, even
 * though JDK has exactly one of each today (docs/modules/machines.md
 * #2) -- composed identically to CategoriesPage. `code` is
 * system-generated and immutable -- there is no Code input on Create;
 * the Edit dialog shows it disabled purely for reference. */
export function ProductionLinesPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [editingLine, setEditingLine] = useState<ProductionLine | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<ProductionLine | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<LineFormValues>({ resolver: zodResolver(lineSchema), defaultValues: emptyDefaults })

  const table = useServerTable<ProductionLine, ProductionLinesFilters>({
    fetcher: fetchProductionLines,
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

  function openCreate() {
    setEditingLine(null)
    reset(emptyDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(line: ProductionLine) {
    setEditingLine(line)
    reset(toFormValues(line))
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: LineFormValues) => {
      setFormError(null)
      try {
        if (editingLine) {
          await apiClient.patch(`/api/production-lines/${editingLine.id}`, { name: values.name })
        } else {
          await apiClient.post('/api/production-lines', values)
        }
        setFormOpen(false)
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof LineFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingLine, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/production-lines/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<ProductionLine>[] = [
    { key: 'code', label: 'Code', sortable: true, render: (l) => l.code },
    { key: 'name', label: 'Production Line', sortable: true, render: (l) => l.name },
    {
      key: 'status',
      label: 'Status',
      render: (l) => <Badge tone={l.is_active ? 'success' : 'danger'}>{l.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (l: ProductionLine) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(l) },
                l.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(l) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(l) },
              ]
              return <ActionMenu label={`Actions for ${l.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Production Lines"
        subtitle="The production flow/resource each Machine runs on."
        actions={canManage ? <Button onClick={openCreate}>New Production Line</Button> : undefined}
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
        rowKey={(l) => l.id}
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
        emptyTitle={debouncedSearch ? 'No matching production lines' : 'No production lines yet'}
        emptyMessage={
          debouncedSearch
            ? 'Try a different search term.'
            : canManage
              ? 'Create the first production line with the New Production Line button above.'
              : 'No production lines have been created yet.'
        }
      />

      {canManage && (
        <>
          <FormDialog
            open={formOpen}
            title={editingLine ? 'Edit Production Line' : 'New Production Line'}
            onClose={() => setFormOpen(false)}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingLine ? 'Save' : 'Create production line'}
          >
            <Alert variant="danger">{formError}</Alert>
            {editingLine && (
              <TextField label="Code" disabled readOnly hint="System-generated. Cannot be changed." value={editingLine.code} />
            )}
            <TextField label="Name" required {...register('name')} error={errors.name?.message} />
          </FormDialog>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate production line' : 'Activate production line'}
            message={
              statusTarget?.is_active
                ? `${statusTarget.name} will no longer be selectable for new machines. Existing machines that reference it are unaffected.`
                : `${statusTarget?.name ?? ''} will be selectable for new machines again.`
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
