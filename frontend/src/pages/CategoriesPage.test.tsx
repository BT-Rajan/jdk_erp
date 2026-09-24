import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { CategoriesPage } from './CategoriesPage'

const { useAuthMock, getMock, postMock, patchMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})

const ADMIN = { id: 1, full_name: 'Admin User', role: 'admin' }
const TEAM_MEMBER = { id: 2, full_name: 'Team Member', role: 'team_member' }

function makeCategory(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    name: 'Electronics',
    code: 'ELEC',
    description: 'Electronic parts',
    is_active: true,
    ...overrides,
  }
}

function categoriesResponse(
  data: ReturnType<typeof makeCategory>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  getMock.mockResolvedValue({ data: categoriesResponse([makeCategory()]) })
})

describe('CategoriesPage', () => {
  it('loads and renders categories on mount, with exactly one initial request', async () => {
    render(<CategoriesPage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Electronics')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/categories')
    expect(calls).toHaveLength(1)
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<CategoriesPage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Electronics')).toBeInTheDocument()
    // Categories is open-read (docs/modules/categories.md #5) -- a
    // non-admin still sees the list, just none of the mutating affordances.
    expect(screen.queryByRole('button', { name: 'New Category' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockRejectedValue(new Error('Network down'))
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no categories at all vs. no search matches', async () => {
    getMock.mockResolvedValue({ data: categoriesResponse([]) })
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('No categories yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching categories')).toBeInTheDocument())
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Electronics')
    getMock.mockClear()

    await userEvent.type(screen.getByLabelText('Search'), 'elec')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/categories')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/categories')!
    expect(config.params.q).toBe('elec')
    expect(config.params.page).toBe(1)
  })

  it('creating a category posts the payload and refetches the list', async () => {
    postMock.mockResolvedValue({ data: makeCategory({ id: 2, name: 'Hardware' }) })
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Electronics')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Category' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Hardware')
    await userEvent.click(screen.getByRole('button', { name: 'Create category' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/categories', expect.objectContaining({ name: 'Hardware' })),
    )
    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/categories')
      expect(calls.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('creating a category shows a server-side field/name conflict as a form error', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(new ApiError({ message: 'A category with this name or code already exists.', code: 'CONFLICT' }, 409))
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Electronics')

    await userEvent.click(screen.getByRole('button', { name: 'New Category' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Electronics')
    await userEvent.click(screen.getByRole('button', { name: 'Create category' }))

    expect(await screen.findByText('A category with this name or code already exists.')).toBeInTheDocument()
  })

  it('editing a category pre-fills the form and sends a PATCH', async () => {
    patchMock.mockResolvedValue({ data: makeCategory({ name: 'Consumer Electronics' }) })
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Electronics')

    const row = screen.getByText('Electronics').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Name')).toHaveValue('Electronics')
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Consumer Electronics')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/categories/1',
        expect.objectContaining({ name: 'Consumer Electronics' }),
      ),
    )
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeCategory({ is_active: false }) })
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Electronics')

    const row = screen.getByText('Electronics').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/categories/1/status', { is_active: false }))
  })

  it('shows an error message when changing status fails', async () => {
    patchMock.mockRejectedValue(new Error('Failed to change status.'))
    render(<CategoriesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Electronics')

    const row = screen.getByText('Electronics').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByText('Failed to change status.')).toBeInTheDocument()
  })
})
