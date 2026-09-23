import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProductsPage } from './ProductsPage'

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

const CATEGORIES_RESPONSE = {
  data: [{ id: 10, name: 'Electronics', code: 'ELEC', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}
const UNITS_RESPONSE = {
  data: [{ id: 20, name: 'Kilogram', code: 'KG', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function makeProduct(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    code: 'PRD001',
    name: 'Widget',
    category_id: 10,
    unit_of_measure_id: 20,
    description: null,
    selling_price: '149.99',
    manufacturing_lead_time_days: 10,
    customer_lead_time_days: 15,
    is_active: true,
    ...overrides,
  }
}

function productsResponse(
  data: ReturnType<typeof makeProduct>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
    if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
    if (url === '/api/products') return Promise.resolve({ data: productsResponse([makeProduct()]) })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('ProductsPage', () => {
  it('loads and renders products on mount, with exactly one initial request', async () => {
    render(<ProductsPage />)

    expect(await screen.findByText('Widget')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/products')
    expect(calls).toHaveLength(1)
  })

  it('shows the category name and unit code resolved from the lookup lists', async () => {
    render(<ProductsPage />)
    expect(await screen.findByText('Electronics')).toBeInTheDocument()
    expect(await screen.findByText('KG')).toBeInTheDocument()
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<ProductsPage />)

    expect(await screen.findByText('Widget')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Product' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
    // team_member never fetches the category/unit lookups -- no manage capability.
    expect(getMock.mock.calls.some(([url]) => url === '/api/categories')).toBe(false)
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })
    render(<ProductsPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no products at all vs. no search matches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/categories') return Promise.resolve({ data: CATEGORIES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.resolve({ data: productsResponse([]) })
    })
    render(<ProductsPage />)
    expect(await screen.findByText('No products yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching products')).toBeInTheDocument())
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<ProductsPage />)
    await screen.findByText('Widget')
    getMock.mockClear()

    await userEvent.type(screen.getByLabelText('Search'), 'widg')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/products')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/products')!
    expect(config.params.q).toBe('widg')
    expect(config.params.page).toBe(1)
  })

  it('creating a product posts the payload including code, category, unit and lead times', async () => {
    postMock.mockResolvedValue({ data: makeProduct({ id: 2, name: 'Gizmo', code: 'PRD002' }) })
    render(<ProductsPage />)
    await screen.findByText('Widget')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Product' }))
    await userEvent.type(screen.getByLabelText('Product Code'), 'PRD002')
    await userEvent.type(screen.getByLabelText('Product Name'), 'Gizmo')
    await userEvent.selectOptions(screen.getByLabelText('Category'), '10')
    await userEvent.selectOptions(screen.getByLabelText('Unit of Measure'), '20')
    await userEvent.type(screen.getByLabelText('Default Selling Price'), '199.99')
    await userEvent.type(screen.getByLabelText('Manufacturing Lead Time (days)'), '5')
    await userEvent.type(screen.getByLabelText('Customer Lead Time (days)'), '7')
    await userEvent.click(screen.getByRole('button', { name: 'Create product' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/products',
        expect.objectContaining({
          code: 'PRD002',
          name: 'Gizmo',
          category_id: 10,
          unit_of_measure_id: 20,
          selling_price: '199.99',
          manufacturing_lead_time_days: 5,
          customer_lead_time_days: 7,
        }),
      ),
    )
  })

  it('rejects a non-numeric selling price inline before submitting', async () => {
    render(<ProductsPage />)
    await screen.findByText('Widget')

    await userEvent.click(screen.getByRole('button', { name: 'New Product' }))
    await userEvent.type(screen.getByLabelText('Product Code'), 'PRD002')
    await userEvent.type(screen.getByLabelText('Product Name'), 'Gizmo')
    await userEvent.selectOptions(screen.getByLabelText('Category'), '10')
    await userEvent.selectOptions(screen.getByLabelText('Unit of Measure'), '20')
    await userEvent.type(screen.getByLabelText('Default Selling Price'), 'not-a-number')
    await userEvent.click(screen.getByRole('button', { name: 'Create product' }))

    expect(await screen.findByText('Enter a valid amount')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('creating a product shows a server-side code conflict as a form error', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(new ApiError({ message: 'A product with this code or name already exists.', code: 'CONFLICT' }, 409))
    render(<ProductsPage />)
    await screen.findByText('Widget')

    await userEvent.click(screen.getByRole('button', { name: 'New Product' }))
    await userEvent.type(screen.getByLabelText('Product Code'), 'PRD001')
    await userEvent.type(screen.getByLabelText('Product Name'), 'Duplicate')
    await userEvent.selectOptions(screen.getByLabelText('Category'), '10')
    await userEvent.selectOptions(screen.getByLabelText('Unit of Measure'), '20')
    await userEvent.type(screen.getByLabelText('Default Selling Price'), '10.00')
    await userEvent.click(screen.getByRole('button', { name: 'Create product' }))

    expect(await screen.findByText('A product with this code or name already exists.')).toBeInTheDocument()
  })

  it('editing a product pre-fills the form, disables the code field, and sends a PATCH without code', async () => {
    patchMock.mockResolvedValue({ data: makeProduct({ name: 'Super Widget' }) })
    render(<ProductsPage />)
    await screen.findByText('Widget')

    const row = screen.getByText('Widget').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Product Code')).toHaveValue('PRD001')
    expect(screen.getByLabelText('Product Code')).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Product Name'))
    await userEvent.type(screen.getByLabelText('Product Name'), 'Super Widget')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/products/1',
        expect.not.objectContaining({ code: expect.anything() }),
      ),
    )
    const [, payload] = patchMock.mock.calls[0]
    expect(payload.name).toBe('Super Widget')
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeProduct({ is_active: false }) })
    render(<ProductsPage />)
    await screen.findByText('Widget')

    const row = screen.getByText('Widget').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/products/1/status', { is_active: false }))
  })

  it('shows an error message when changing status fails', async () => {
    patchMock.mockRejectedValue(new Error('Failed to change status.'))
    render(<ProductsPage />)
    await screen.findByText('Widget')

    const row = screen.getByText('Widget').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByText('Failed to change status.')).toBeInTheDocument()
  })
})
