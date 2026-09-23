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

/** Mirrors backend/app/schemas/supplier.py's SupplierOut. */
interface Supplier {
  id: number
  organisation_id: number
  code: string
  name: string
  contact_person: string | null
  phone: string | null
  email: string | null
  address: string | null
  is_active: boolean
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface SuppliersFilters {
  search: string
}

const supplierSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  contact_person: z.string(),
  phone: z.string(),
  email: z.string().refine((value) => value === '' || z.string().email().safeParse(value).success, 'Enter a valid email address'),
  address: z.string(),
})

type SupplierFormValues = z.infer<typeof supplierSchema>

const emptyDefaults: SupplierFormValues = { name: '', contact_person: '', phone: '', email: '', address: '' }

function toFormValues(supplier: Supplier): SupplierFormValues {
  return {
    name: supplier.name,
    contact_person: supplier.contact_person ?? '',
    phone: supplier.phone ?? '',
    email: supplier.email ?? '',
    address: supplier.address ?? '',
  }
}

async function fetchSuppliers({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: SuppliersFilters
}): Promise<ServerTableResult<Supplier>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  const { data } = await apiClient.get<PaginatedResponse<Supplier>>('/api/suppliers', {
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

/** The vendor master consumed by Procurement once it's built
 * (backend/app/api/suppliers.py, docs/modules/suppliers.md). Deliberately
 * the lightest master-data page so far -- expected volume is ~10
 * suppliers per organisation. Read is open to any authenticated
 * organisation member, same as Categories/Units of Measure; create/edit/
 * activate-deactivate are admin-gated, same shape as Categories (not
 * Customer's ownership-scoped/permission-engine shape -- a supplier has
 * no assignment dimension). Composed from the same common list
 * foundation as every other master-data page. */
export function SuppliersPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [editingSupplier, setEditingSupplier] = useState<Supplier | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Supplier | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<SupplierFormValues>({ resolver: zodResolver(supplierSchema), defaultValues: emptyDefaults })

  const table = useServerTable<Supplier, SuppliersFilters>({
    fetcher: fetchSuppliers,
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
    setEditingSupplier(null)
    reset(emptyDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(supplier: Supplier) {
    setEditingSupplier(supplier)
    reset(toFormValues(supplier))
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: SupplierFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        contact_person: values.contact_person || null,
        phone: values.phone || null,
        email: values.email || null,
        address: values.address || null,
      }
      try {
        if (editingSupplier) {
          await apiClient.patch(`/api/suppliers/${editingSupplier.id}`, payload)
        } else {
          await apiClient.post('/api/suppliers', payload)
        }
        setFormOpen(false)
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof SupplierFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingSupplier, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/suppliers/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<Supplier>[] = [
    { key: 'code', label: 'Code', sortable: true, hideBelow: 'sm', render: (s) => s.code },
    { key: 'name', label: 'Supplier', sortable: true, render: (s) => s.name },
    {
      key: 'contact',
      label: 'Contact',
      hideBelow: 'md',
      render: (s) => s.contact_person || s.phone || s.email || <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'status',
      label: 'Status',
      render: (s) => <Badge tone={s.is_active ? 'success' : 'danger'}>{s.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (s: Supplier) => {
              const options: ActionMenuOption[] = [
                { key: 'edit', label: 'Edit', onSelect: () => openEdit(s) },
                s.is_active
                  ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(s) }
                  : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(s) },
              ]
              return <ActionMenu label={`Actions for ${s.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Suppliers"
        subtitle="The vendor master consumed by Procurement."
        actions={canManage ? <Button onClick={openCreate}>New Supplier</Button> : undefined}
      />

      <Alert variant="danger">{pageError}</Alert>

      <FilterBar>
        <TextField
          label="Search"
          placeholder="Search by name, code, contact or phone..."
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
        />
      </FilterBar>

      <DataTable
        columns={columns}
        rows={table.rows}
        rowKey={(s) => s.id}
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
        emptyTitle={debouncedSearch ? 'No matching suppliers' : 'No suppliers yet'}
        emptyMessage={
          debouncedSearch
            ? 'Try a different search term.'
            : canManage
              ? 'Create the first supplier with the New Supplier button above.'
              : 'No suppliers have been created yet.'
        }
      />

      {canManage && (
        <>
          <FormDialog
            open={formOpen}
            title={editingSupplier ? 'Edit Supplier' : 'New Supplier'}
            onClose={() => setFormOpen(false)}
            onSubmit={handleSubmit(onFormSubmit)}
            submitting={isSubmitting}
            submitLabel={editingSupplier ? 'Save' : 'Create supplier'}
          >
            <Alert variant="danger">{formError}</Alert>
            <TextField label="Name" required {...register('name')} error={errors.name?.message} />
            <TextField label="Contact person" {...register('contact_person')} error={errors.contact_person?.message} />
            <TextField label="Phone" {...register('phone')} error={errors.phone?.message} />
            <TextField label="Email" type="email" {...register('email')} error={errors.email?.message} />
            <TextareaField label="Address" {...register('address')} error={errors.address?.message} />
          </FormDialog>

          <ConfirmDialog
            open={!!statusTarget}
            title={statusTarget?.is_active ? 'Deactivate supplier' : 'Activate supplier'}
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
