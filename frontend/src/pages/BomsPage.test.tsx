import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BomsPage } from './BomsPage'

const { useAuthMock, getMock, postMock, patchMock, deleteMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
  deleteMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock, delete: deleteMock } }
})

const ADMIN = { id: 1, full_name: 'Admin User', role: 'admin' }
const TEAM_MEMBER = { id: 2, full_name: 'Team Member', role: 'team_member' }

const PRODUCTS_RESPONSE = {
  data: [{ id: 10, code: 'PRD-TON', name: 'Product A', unit_of_measure_id: 30, is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}
const MATERIALS_RESPONSE = {
  data: [{ id: 20, code: 'RM-M', name: 'Material M', unit_of_measure_id: 31, is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}
const UNITS_RESPONSE = {
  data: [
    { id: 30, name: 'Tonne', code: 'TON', is_active: true },
    { id: 31, name: 'Kilogram', code: 'KG', is_active: true },
  ],
  pagination: { page: 1, page_size: 200, total: 2, total_pages: 2 },
}

function makeBom(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    product_id: 10,
    base_quantity: '1.0000',
    status: 'draft',
    notes: null,
    components: [],
    ...overrides,
  }
}

function bomsResponse(
  data: ReturnType<typeof makeBom>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  deleteMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
    if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
    if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
    if (url === '/api/boms') return Promise.resolve({ data: bomsResponse([makeBom()]) })
    if (url === '/api/boms/1') return Promise.resolve({ data: makeBom() })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('BomsPage', () => {
  it('loads and renders BOMs on mount, resolving the product name/code', async () => {
    render(<BomsPage />)
    expect(await screen.findByText('Product A (PRD-TON)')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/boms')
    expect(calls).toHaveLength(1)
  })

  it('shows the base quantity with the product\'s own unit', async () => {
    render(<BomsPage />)
    expect(await screen.findByText('1.0000 TON')).toBeInTheDocument()
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<BomsPage />)

    expect(await screen.findByText('Product A (PRD-TON)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New BOM' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Actions for/ }))
    expect(screen.queryByText('Edit')).not.toBeInTheDocument()
    expect(screen.queryByText('Manage Components...')).not.toBeInTheDocument()
    expect(screen.getByText('Calculate Requirements...')).toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })
    render(<BomsPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no BOMs at all vs. no search matches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.resolve({ data: bomsResponse([]) })
    })
    render(<BomsPage />)
    expect(await screen.findByText('No BOMs yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching BOMs')).toBeInTheDocument())
  })

  it('creating a BOM posts product_id, base_quantity, and notes', async () => {
    postMock.mockResolvedValue({ data: makeBom({ id: 2 }) })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New BOM' }))
    await userEvent.selectOptions(screen.getByLabelText('Product'), '10')
    await userEvent.type(screen.getByLabelText('Base Quantity'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Create BOM' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/boms', {
        product_id: 10,
        base_quantity: '1',
        notes: null,
      }),
    )
  })

  it('rejects a non-positive base quantity inline before submitting', async () => {
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    await userEvent.click(screen.getByRole('button', { name: 'New BOM' }))
    await userEvent.selectOptions(screen.getByLabelText('Product'), '10')
    await userEvent.type(screen.getByLabelText('Base Quantity'), '0')
    await userEvent.click(screen.getByRole('button', { name: 'Create BOM' }))

    expect(await screen.findByText('Enter a positive number')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('editing a BOM disables the product field and patches only base_quantity/notes', async () => {
    patchMock.mockResolvedValue({ data: makeBom({ base_quantity: '2.0000' }) })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Product')).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Base Quantity'))
    await userEvent.type(screen.getByLabelText('Base Quantity'), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/boms/1', { base_quantity: '2', notes: null }),
    )
  })

  it('activating a draft BOM calls the status endpoint with status: active', async () => {
    patchMock.mockResolvedValue({ data: makeBom({ status: 'active' }) })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Activate'))
    await userEvent.click(screen.getByRole('button', { name: 'Activate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/boms/1/status', { status: 'active' }))
  })

  it('managing components: adding a component posts raw_material_id and quantity, then refetches the BOM', async () => {
    postMock.mockResolvedValue({ data: makeBom() })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Components...'))

    await userEvent.click(await screen.findByRole('button', { name: 'Add Component' }))
    await userEvent.selectOptions(screen.getByLabelText('Raw Material'), '20')
    await userEvent.type(screen.getByLabelText('Quantity'), '600')
    await userEvent.click(screen.getByRole('button', { name: 'Add component' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/boms/1/components', {
        raw_material_id: 20,
        quantity: '600',
      }),
    )
    await waitFor(() => expect(getMock.mock.calls.some(([url]) => url === '/api/boms/1')).toBe(true))
  })

  it('managing components: shows conversion status and percentage for an existing component', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      const withComponent = makeBom({
        components: [
          { id: 1, raw_material_id: 20, quantity: '600.0000', percentage: '60.00000000', conversion_ok: true, conversion_error: null },
        ],
      })
      if (url === '/api/boms') return Promise.resolve({ data: bomsResponse([withComponent]) })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Components...'))

    expect(await screen.findByText('Material M')).toBeInTheDocument()
    expect(screen.getByText('60.00%')).toBeInTheDocument()
    expect(screen.getByText('OK')).toBeInTheDocument()
  })

  it('removing a component asks for confirmation, then calls delete and refetches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      const withComponent = makeBom({
        components: [
          { id: 1, raw_material_id: 20, quantity: '600.0000', percentage: '60.00000000', conversion_ok: true, conversion_error: null },
        ],
      })
      if (url === '/api/boms') return Promise.resolve({ data: bomsResponse([withComponent]) })
      if (url === '/api/boms/1') return Promise.resolve({ data: makeBom() })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    deleteMock.mockResolvedValue({ data: null })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Manage Components...'))
    await screen.findByText('Material M')

    await userEvent.click(screen.getByRole('button', { name: 'Actions for Material M' }))
    await userEvent.click(await screen.findByText('Remove'))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith('/api/boms/1/components/1'))
  })

  it('calculating requirements posts the production quantity and renders the resulting table', async () => {
    postMock.mockResolvedValue({
      data: {
        product_id: 10,
        production_quantity: '2.5',
        requirements: [{ raw_material_id: 20, required_quantity: '1500.0000', unit_of_measure_id: 31 }],
      },
    })
    getMock.mockImplementation((url: string) => {
      if (url === '/api/products') return Promise.resolve({ data: PRODUCTS_RESPONSE })
      if (url === '/api/raw-materials') return Promise.resolve({ data: MATERIALS_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      if (url === '/api/boms') return Promise.resolve({ data: bomsResponse([makeBom({ status: 'active' })]) })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Calculate Requirements...'))

    await userEvent.type(screen.getByLabelText('Production Quantity'), '2.5')
    await userEvent.click(screen.getByRole('button', { name: 'Calculate' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/boms/1/calculate-requirements', { production_quantity: '2.5' }),
    )
    expect(await screen.findByText('1500.0000')).toBeInTheDocument()
    expect(screen.getByText('Material M')).toBeInTheDocument()
  })

  it('warns that only an active BOM can calculate requirements when the BOM is still draft', async () => {
    render(<BomsPage />)
    await screen.findByText('Product A (PRD-TON)')

    const row = screen.getByText('Product A (PRD-TON)').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Calculate Requirements...'))

    expect(
      await screen.findByText('Only an active BOM can be used to calculate production requirements.'),
    ).toBeInTheDocument()
  })
})
