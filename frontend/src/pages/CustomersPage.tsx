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
import { FormDialog } from '@/components/ui/FormDialog'
import { PageHeader } from '@/components/ui/PageHeader'
import type { SortState } from '@/components/ui/sort'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { MANAGER, isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'

/** Mirrors backend/app/schemas/customer.py's CustomerOut. */
interface Customer {
  id: number
  organisation_id: number
  code: string
  name: string
  contact_person: string | null
  phone: string | null
  email: string | null
  address: string | null
  assigned_to_user_id: number | null
  is_active: boolean
}

/** Local shape for the assignee picker -- mirrors the fields this page
 * actually needs from backend/app/schemas/user.py's UserOut, not the
 * whole record. */
interface AssignableUser {
  id: number
  full_name: string
  role: string
}

interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

interface CustomersFilters {
  search: string
}

const customerSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  contact_person: z.string(),
  phone: z.string(),
  email: z.string().refine((value) => value === '' || z.string().email().safeParse(value).success, 'Enter a valid email address'),
  address: z.string(),
})

type CustomerFormValues = z.infer<typeof customerSchema>

const emptyDefaults: CustomerFormValues = { name: '', contact_person: '', phone: '', email: '', address: '' }

function toFormValues(customer: Customer): CustomerFormValues {
  return {
    name: customer.name,
    contact_person: customer.contact_person ?? '',
    phone: customer.phone ?? '',
    email: customer.email ?? '',
    address: customer.address ?? '',
  }
}

async function fetchCustomers({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: CustomersFilters
}): Promise<ServerTableResult<Customer>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md).
  // Which rows come back is further narrowed server-side by the
  // caller's own OWN/TEAM/ALL view scope (docs/modules/customers.md #4)
  // -- this page never re-implements that filtering client-side.
  const { data } = await apiClient.get<PaginatedResponse<Customer>>('/api/customers', {
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

/** The single authoritative customer record consumed by Sales
 * (backend/app/api/customers.py, docs/modules/customers.md). Unlike
 * Categories/Units, this list is never "open to everyone, unfiltered" --
 * the backend already narrows every response to the caller's resolved
 * OWN/TEAM/ALL scope, so a team_member simply never receives another
 * salesperson's customers to begin with (Principle 3: enforcement is
 * server-side; nothing here re-derives or trusts a client-side filter).
 * Any authenticated user can create a customer (ordinary sales work);
 * editing and activate/deactivate are admin-only; reassigning a
 * customer is admin-or-manager. Composed from the same common list
 * foundation as CategoriesPage/UnitsOfMeasurePage. */
export function CustomersPage() {
  const { user: currentUser } = useAuth()
  const canEdit = isAdminRole(currentUser?.role)
  const canAssign = canEdit || currentUser?.role === MANAGER

  const [users, setUsers] = useState<AssignableUser[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [formOpen, setFormOpen] = useState(false)
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<Customer | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const [assignTarget, setAssignTarget] = useState<Customer | null>(null)
  const [assignValue, setAssignValue] = useState<string>('')
  const [assignBusy, setAssignBusy] = useState(false)
  const [assignError, setAssignError] = useState<string | undefined>(undefined)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<CustomerFormValues>({ resolver: zodResolver(customerSchema), defaultValues: emptyDefaults })

  const table = useServerTable<Customer, CustomersFilters>({
    fetcher: fetchCustomers,
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

  const usersById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users])

  const loadUsers = useCallback(async () => {
    try {
      const { data } = await apiClient.get<PaginatedResponse<AssignableUser>>('/api/users', {
        params: { page_size: 200 },
      })
      setUsers(data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load users.')
    }
  }, [])

  useEffect(() => {
    if (canAssign) void loadUsers()
  }, [canAssign, loadUsers])

  function openCreate() {
    setEditingCustomer(null)
    reset(emptyDefaults)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(customer: Customer) {
    setEditingCustomer(customer)
    reset(toFormValues(customer))
    setFormError(null)
    setFormOpen(true)
  }

  const onFormSubmit = useCallback(
    async (values: CustomerFormValues) => {
      setFormError(null)
      const payload = {
        name: values.name,
        contact_person: values.contact_person || null,
        phone: values.phone || null,
        email: values.email || null,
        address: values.address || null,
      }
      try {
        if (editingCustomer) {
          await apiClient.patch(`/api/customers/${editingCustomer.id}`, payload)
        } else {
          await apiClient.post('/api/customers', payload)
        }
        setFormOpen(false)
        table.refetch()
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.fields) {
            for (const [field, message] of Object.entries(err.fields)) {
              if (field in emptyDefaults) setFieldError(field as keyof CustomerFormValues, { message })
            }
          }
          setFormError(err.message)
        } else {
          setFormError('Something went wrong. Please try again.')
        }
      }
    },
    [editingCustomer, setFieldError, table],
  )

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/customers/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  function openAssign(customer: Customer) {
    setAssignTarget(customer)
    setAssignValue(customer.assigned_to_user_id ? String(customer.assigned_to_user_id) : '')
    setAssignError(undefined)
  }

  async function confirmAssign() {
    if (!assignTarget) return
    setAssignBusy(true)
    setAssignError(undefined)
    try {
      await apiClient.patch(`/api/customers/${assignTarget.id}/assign`, {
        assigned_to_user_id: assignValue ? Number(assignValue) : null,
      })
      setAssignTarget(null)
      table.refetch()
    } catch (err) {
      setAssignError(err instanceof ApiError ? err.message : 'Failed to assign customer.')
    } finally {
      setAssignBusy(false)
    }
  }

  const columns: DataTableColumn<Customer>[] = [
    { key: 'code', label: 'Code', sortable: true, hideBelow: 'sm', render: (c) => c.code },
    { key: 'name', label: 'Customer', sortable: true, render: (c) => c.name },
    {
      key: 'contact',
      label: 'Contact',
      hideBelow: 'md',
      render: (c) => c.contact_person || c.phone || c.email || <span className="text-gold-100/40">—</span>,
    },
    {
      key: 'assigned_to',
      label: 'Assigned To',
      hideBelow: 'lg',
      render: (c) =>
        c.assigned_to_user_id ? (
          (usersById.get(c.assigned_to_user_id)?.full_name ?? `#${c.assigned_to_user_id}`)
        ) : (
          <span className="text-gold-100/40">Unassigned</span>
        ),
    },
    {
      key: 'status',
      label: 'Status',
      render: (c) => <Badge tone={c.is_active ? 'success' : 'danger'}>{c.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    ...(canEdit || canAssign
      ? [
          {
            key: 'actions',
            label: '',
            alwaysVisible: true,
            align: 'right' as const,
            render: (c: Customer) => {
              const options: ActionMenuOption[] = []
              if (canEdit) options.push({ key: 'edit', label: 'Edit', onSelect: () => openEdit(c) })
              if (canAssign) options.push({ key: 'assign', label: 'Assign...', onSelect: () => openAssign(c) })
              if (canEdit) {
                options.push(
                  c.is_active
                    ? { key: 'deactivate', label: 'Deactivate', danger: true, onSelect: () => setStatusTarget(c) }
                    : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(c) },
                )
              }
              return <ActionMenu label={`Actions for ${c.name}`} options={options} />
            },
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Customers"
        subtitle="The authoritative customer record consumed by Sales."
        actions={<Button onClick={openCreate}>New Customer</Button>}
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
        emptyTitle={debouncedSearch ? 'No matching customers' : 'No customers yet'}
        emptyMessage={
          debouncedSearch ? 'Try a different search term.' : 'Create the first customer with the New Customer button above.'
        }
      />

      <FormDialog
        open={formOpen}
        title={editingCustomer ? 'Edit Customer' : 'New Customer'}
        onClose={() => setFormOpen(false)}
        onSubmit={handleSubmit(onFormSubmit)}
        submitting={isSubmitting}
        submitLabel={editingCustomer ? 'Save' : 'Create customer'}
      >
        <Alert variant="danger">{formError}</Alert>
        <TextField label="Name" required {...register('name')} error={errors.name?.message} />
        <TextField label="Contact person" {...register('contact_person')} error={errors.contact_person?.message} />
        <TextField label="Phone" {...register('phone')} error={errors.phone?.message} />
        <TextField label="Email" type="email" {...register('email')} error={errors.email?.message} />
        <TextareaField label="Address" {...register('address')} error={errors.address?.message} />
      </FormDialog>

      {canEdit && (
        <ConfirmDialog
          open={!!statusTarget}
          title={statusTarget?.is_active ? 'Deactivate customer' : 'Activate customer'}
          message={
            statusTarget?.is_active
              ? `${statusTarget.name} will no longer be selectable for new sales records. Existing records are unaffected.`
              : `${statusTarget?.name ?? ''} will be selectable for new sales records again.`
          }
          confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
          danger={statusTarget?.is_active}
          busy={statusBusy}
          onConfirm={confirmStatusChange}
          onCancel={() => setStatusTarget(null)}
        />
      )}

      {canAssign && (
        <FormDialog
          open={!!assignTarget}
          title={`Assign ${assignTarget?.name ?? ''}`}
          onClose={() => setAssignTarget(null)}
          onSubmit={(event) => {
            event.preventDefault()
            void confirmAssign()
          }}
          submitting={assignBusy}
          submitLabel="Save assignment"
        >
          <Alert variant="danger">{assignError}</Alert>
          <SelectField label="Assigned to" value={assignValue} onChange={(event) => setAssignValue(event.target.value)}>
            <option value="">Unassigned</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </SelectField>
        </FormDialog>
      )}
    </div>
  )
}
