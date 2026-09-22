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
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/category.py's CategoryOut. */
interface Category {
  id: number
  organisation_id: number
  name: string
  code: string | null
  description: string | null
  is_active: boolean
}

/** Mirrors backend/app/schemas/pagination.py's PaginatedResponse -- the
 * one shape every server-backed list endpoint returns
 * (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's list-contract
 * follow-up). */
interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface CategoriesFilters {
  search: string
}

const categorySchema = z.object({
  name: z.string().min(1, 'Name is required'),
  code: z.string(),
  description: z.string(),
})

type CategoryFormValues = z.infer<typeof categorySchema>

const emptyDefaults: CategoryFormValues = { name: '', code: '', description: '' }

function toFormValues(category: Category): CategoryFormValues {
  return { name: category.name, code: category.code ?? '', description: category.description ?? '' }
}

async function fetchCategories({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: CategoriesFilters
}): Promise<ServerTableResult<Category>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md):
  // page/page_size/sort_by/sort_direction/q, all applied server-side to
  // the same organisation-scoped query.
  const { data } = await apiClient.get<PaginatedResponse<Category>>('/api/categories', {
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

/** The single authoritative classification master for Products/Raw
 * Materials (backend/app/api/categories.py, docs/modules/categories.md).
 * Read is open to any authenticated organisation member -- category is
 * reference data every future master-data module looks up, not a
 * privileged view -- but create/edit/activate-deactivate are
 * admin-gated, same as every other master-data mutation in this app.
 * Server-side is the real boundary (Principle 3); hiding the mutating
 * controls for a non-admin here is a usability courtesy, not the
 * enforcement itself. First real consumer of the common list foundation
 * in Phase 2 (Master Data), composed exactly like UsersPage. */
export function CategoriesPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Category | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<CategoryFormValues>({ resolver: zodResolver(categorySchema), defaultValues: emptyDefaults })

  const table = useServerTable<Category, CategoriesFilters>({
    fetcher: fetchCategories,
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

  function openCreate() {
    setEditingCategory(null)
    reset(emptyDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(category: Category) {
    setEditingCategory(category)
    reset(toFormValues(category))
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: CategoryFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        code: values.code || null,
        description: values.description || null,
      }
      try {
        if (editingCategory) {
          await apiClient.patch(`/api/categories/${editingCategory.id}`, payload)
        } else {
          await apiClient.post('/api/categories', payload)
        }
        setFormOpen(false)
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof CategoryFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingCategory, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/categories/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<Category>[] = [
    { key: 'name', label: 'Name', sortable: true, render: (c) => c.name },
    { key: 'code', label: 'Code', sortable: true, hideBelow: 'sm', render: (c) => c.code ?? <span className="text-gold-100/40">—</span> },
    {
      key: 'description',
      label: 'Description',
      hideBelow: 'md',
      render: (c) => c.description ?? <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'status',
      label: 'Status',
      render: (c) => <Badge tone={c.is_active ? 'success' : 'danger'}>{c.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (c: Category) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(c) },
                c.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(c) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(c) },
              ]
              return <ActionMenu label={`Actions for ${c.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Categories"
        subtitle="The classification master used to group Products and Raw Materials."
        actions={canManage ? <Button onClick={openCreate}>New Category</Button> : undefined}
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
        rowKey={(c) => c.id}
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
        emptyTitle={debouncedSearch ? 'No matching categories' : 'No categories yet'}
        emptyMessage={
          debouncedSearch
            ? 'Try a different search term.'
            : canManage
              ? 'Create the first category with the New Category button above.'
              : 'No categories have been created yet.'
        }
      />

      {canManage && (
        <>
          <FormDialog
            open={formOpen}
            title={editingCategory ? 'Edit Category' : 'New Category'}
            onClose={() => setFormOpen(false)}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingCategory ? 'Save' : 'Create category'}
          >
            <Alert variant="danger">{formError}</Alert>
            <TextField label="Name" required {...register('name')} error={errors.name?.message} />
            <TextField label="Code" hint="Optional short code." {...register('code')} error={errors.code?.message} />
            <TextareaField label="Description" {...register('description')} error={errors.description?.message} />
          </FormDialog>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate category' : 'Activate category'}
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
