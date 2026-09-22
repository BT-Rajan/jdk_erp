import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Controller, useForm } from 'react-hook-form'
import { z } from 'zod'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
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
import { MultiSelectField } from '@/components/forms/MultiSelectField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { ROLE_LABELS, VALID_ROLES, isAdminRole } from '@/lib/auth/roles'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { useServerTable, type ServerTableResult } from '@/lib/useServerTable'
import type { User } from '@/lib/auth/types'

/** Mirrors backend/app/schemas/team.py's TeamOut -- kept local to this
 * page rather than a shared types file since nothing else consumes it
 * yet; extract when a Teams management screen needs the same shape. */
interface Team {
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

interface UsersFilters {
  search: string
}

const createUserSchema = z.object({
  full_name: z.string().min(1, 'Full name is required'),
  email: z.string().email('Enter a valid email address'),
  username: z.string().min(1, 'Username is required'),
  // Mirrors backend/app/core/validation.py's validate_password_complexity
  // -- UI-side validation ahead of the server's authoritative check
  // (docs/modules/common_validation.md), not a replacement for it.
  password: z
    .string()
    .min(8, 'Password must be at least 8 characters long')
    .regex(/[A-Z]/, 'Password must contain at least one uppercase letter')
    .regex(/[0-9]/, 'Password must contain at least one number')
    .regex(/[^A-Za-z0-9]/, 'Password must contain at least one special character'),
  role: z.enum(VALID_ROLES),
  team_ids: z.array(z.number()),
})

type CreateUserValues = z.infer<typeof createUserSchema>

const emptyDefaults: CreateUserValues = {
  full_name: '',
  email: '',
  username: '',
  password: '',
  role: 'team_member',
  team_ids: [],
}

async function fetchUsers({
  page,
  pageSize,
  sort,
  filters,
}: {
  page: number
  pageSize: number
  sort: SortState | null
  filters: UsersFilters
}): Promise<ServerTableResult<User>> {
  // The common list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md):
  // page/page_size/sort_by/sort_direction/q, all applied server-side to
  // the same organisation-scoped query -- this page never fetches
  // everything and filters/sorts it in the browser.
  const { data } = await apiClient.get<PaginatedResponse<User>>('/api/users', {
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

/** Admin-only user directory: list, create, change role, activate/
 * deactivate -- the frontend for the endpoints in backend/app/api/users.py
 * (docs/modules/users.md #4/#6/#10). The first real consumer of the
 * common list foundation (search/sort/pagination via useServerTable,
 * docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md) -- nothing here is
 * Users-specific business logic bleeding into that foundation; this
 * page only supplies its own fetcher, columns, and sortable field
 * names. Server-side is the real boundary (Principle 3); the
 * AccessDeniedState below is a usability courtesy for a non-admin who
 * lands on this route, not the enforcement itself. */
export function UsersPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [teams, setTeams] = useState<Team[]>([])
  const [pageError, setPageError] = useState<string | undefined>(undefined)

  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  const [createOpen, setCreateOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const [statusTarget, setStatusTarget] = useState<User | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<CreateUserValues>({ resolver: zodResolver(createUserSchema), defaultValues: emptyDefaults })

  // useServerTable must be called unconditionally (hooks rules), even
  // though this page renders AccessDeniedState instead of the table
  // for a non-admin below -- guarding inside the fetcher itself is what
  // actually stops a real request firing for someone who can't use
  // this page at all, rather than relying on the component returning
  // early after the fetch has already gone out.
  const fetchUsersGuarded = useCallback(
    (params: Parameters<typeof fetchUsers>[0]) => (canManage ? fetchUsers(params) : Promise.resolve({ rows: [], total: 0 })),
    [canManage],
  )

  const table = useServerTable<User, UsersFilters>({
    fetcher: fetchUsersGuarded,
    pageSize: 20,
    initialFilters: { search: '' },
  })

  // Debounced search feeding into the table's own filter state --
  // changing it resets to page 1 (useServerTable's own contract), the
  // actual server request only fires once typing pauses. Skips its
  // first run: useServerTable already fetches once on mount with
  // `initialFilters`, so calling setFilters again there too would fire
  // a second, redundant request with an identical (but newly-referenced)
  // filters object -- exactly the "no unnecessary reloads" this
  // foundation is meant to prevent.
  const isFirstSearchRender = useRef(true)
  useEffect(() => {
    if (isFirstSearchRender.current) {
      isFirstSearchRender.current = false
      return
    }
    table.setFilters({ search: debouncedSearch })
    // table.setFilters is stable across renders (defined fresh each
    // render but only ever calls setState) -- omitted from deps to
    // avoid re-running on every render; debouncedSearch is the only
    // thing this effect actually reacts to.
  }, [debouncedSearch])

  const teamsById = useMemo(() => new Map(teams.map((team) => [team.id, team])), [teams])

  const loadTeams = useCallback(async () => {
    try {
      const { data } = await apiClient.get<PaginatedResponse<Team>>('/api/teams', {
        params: { include_inactive: true, page_size: 200 },
      })
      setTeams(data.data)
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to load teams.')
    }
  }, [])

  useEffect(() => {
    if (canManage) void loadTeams()
  }, [canManage, loadTeams])

  if (!canManage) {
    return (
      <div className="space-y-6">
        <PageHeader title="Users" />
        <AccessDeniedState message="Only an organisation admin can manage users." />
      </div>
    )
  }

  function openCreate() {
    reset(emptyDefaults)
    setFormError(null)
    setCreateOpen(true)
  }

  async function onCreateSubmit(values: CreateUserValues) {
    setFormError(null)
    try {
      await apiClient.post('/api/users', values)
      setCreateOpen(false)
      table.refetch()
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.fields) {
          for (const [field, message] of Object.entries(err.fields)) {
            if (field in emptyDefaults) setFieldError(field as keyof CreateUserValues, { message })
          }
        }
        setFormError(err.message)
      } else {
        setFormError('Something went wrong. Please try again.')
      }
    }
  }

  async function handleRoleChange(target: User, role: string) {
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/users/${target.id}/role`, { role })
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change role.')
    }
  }

  async function confirmStatusChange() {
    if (!statusTarget) return
    setStatusBusy(true)
    setPageError(undefined)
    try {
      await apiClient.patch(`/api/users/${statusTarget.id}/status`, { is_active: !statusTarget.is_active })
      setStatusTarget(null)
      table.refetch()
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Failed to change status.')
    } finally {
      setStatusBusy(false)
    }
  }

  const columns: DataTableColumn<User>[] = [
    { key: 'full_name', label: 'Name', sortable: true, render: (u) => u.full_name },
    { key: 'email', label: 'Email', sortable: true, hideBelow: 'md', render: (u) => u.email },
    { key: 'username', label: 'Username', sortable: true, hideBelow: 'sm', render: (u) => u.username },
    {
      key: 'role',
      label: 'Role',
      sortable: true,
      render: (u) => <Badge tone="gold">{ROLE_LABELS[u.role] ?? u.role}</Badge>,
    },
    {
      key: 'teams',
      label: 'Teams',
      hideBelow: 'lg',
      render: (u) =>
        u.team_ids.length === 0 ? (
          <span className="text-gold-100/40">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {u.team_ids.map((id) => (
              <Badge key={id}>{teamsById.get(id)?.name ?? `#${id}`}</Badge>
            ))}
          </div>
        ),
    },
    {
      key: 'status',
      label: 'Status',
      render: (u) => <Badge tone={u.is_active ? 'success' : 'danger'}>{u.is_active ? 'Active' : 'Inactive'}</Badge>,
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (u) => {
        const isSelf = u.id === currentUser?.id
        const roleOptions: ActionMenuOption[] = VALID_ROLES.filter((role) => role !== u.role).map((role) => ({
          key: `role-${role}`,
          label: `Set role: ${ROLE_LABELS[role]}`,
          disabled: isSelf,
          onSelect: () => void handleRoleChange(u, role),
        }))
        const statusOption: ActionMenuOption = u.is_active
          ? { key: 'deactivate', label: 'Deactivate', danger: true, disabled: isSelf, onSelect: () => setStatusTarget(u) }
          : { key: 'activate', label: 'Activate', onSelect: () => setStatusTarget(u) }

        return <ActionMenu label={`Actions for ${u.full_name}`} options={[...roleOptions, statusOption]} />
      },
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        subtitle="Create teammates, assign roles and teams, and activate or deactivate accounts."
        actions={<Button onClick={openCreate}>New User</Button>}
      />

      <Alert variant="danger">{pageError}</Alert>

      <FilterBar>
        <TextField
          label="Search"
          placeholder="Search by name, email or username..."
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
        emptyTitle={debouncedSearch ? 'No matching users' : 'No users yet'}
        emptyMessage={debouncedSearch ? 'Try a different search term.' : 'Create the first teammate with the New User button above.'}
      />

      <FormDialog
        open={createOpen}
        title="New User"
        onClose={() => setCreateOpen(false)}
        onSubmit={handleSubmit(onCreateSubmit)}
        submitting={isSubmitting}
        submitLabel="Create user"
      >
        <Alert variant="danger">{formError}</Alert>
        <TextField label="Full name" required {...register('full_name')} error={errors.full_name?.message} />
        <TextField label="Email" type="email" required {...register('email')} error={errors.email?.message} />
        <TextField label="Username" required {...register('username')} error={errors.username?.message} />
        <TextField
          label="Password"
          type="password"
          required
          autoComplete="new-password"
          {...register('password')}
          error={errors.password?.message}
        />
        <SelectField label="Role" required {...register('role')} error={errors.role?.message}>
          {VALID_ROLES.map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role]}
            </option>
          ))}
        </SelectField>
        <Controller
          control={control}
          name="team_ids"
          render={({ field }) => (
            <MultiSelectField
              label="Teams"
              hint="Optional -- hold Ctrl/Cmd to select more than one."
              value={field.value.map(String)}
              onChange={(event) =>
                field.onChange(Array.from(event.target.selectedOptions).map((option) => Number(option.value)))
              }
            >
              {teams
                .filter((team) => team.is_active)
                .map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
            </MultiSelectField>
          )}
        />
      </FormDialog>

      <ConfirmDialog
        open={!!statusTarget}
        title={statusTarget?.is_active ? 'Deactivate user' : 'Activate user'}
        message={
          statusTarget?.is_active
            ? `${statusTarget.full_name} will no longer be able to sign in, and all of their active sessions will be revoked.`
            : `${statusTarget?.full_name ?? ''} will be able to sign in again.`
        }
        confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
        danger={statusTarget?.is_active}
        busy={statusBusy}
        onConfirm={confirmStatusChange}
        onCancel={() => setStatusTarget(null)}
      />
    </div>
  )
}
