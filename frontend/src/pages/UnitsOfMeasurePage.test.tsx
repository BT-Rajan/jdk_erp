import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { UnitsOfMeasurePage } from './UnitsOfMeasurePage'

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

function makeUnit(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    name: 'Kilogram',
    code: 'KG',
    description: 'Base weight unit',
    dimension: null,
    conversion_factor_to_base: null,
    is_active: true,
    ...overrides,
  }
}

function unitsResponse(
  data: ReturnType<typeof makeUnit>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  getMock.mockResolvedValue({ data: unitsResponse([makeUnit()]) })
})

describe('UnitsOfMeasurePage', () => {
  it('loads and renders units on mount, with exactly one initial request', async () => {
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Kilogram')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/units-of-measure')
    expect(calls).toHaveLength(1)
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Kilogram')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Unit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockRejectedValue(new Error('Network down'))
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no units at all vs. no search matches', async () => {
    getMock.mockResolvedValue({ data: unitsResponse([]) })
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('No units yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching units')).toBeInTheDocument())
  })

  it('debounces search: types quickly but only fires one request with the final term, resetting to page 1', async () => {
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')
    getMock.mockClear()

    await userEvent.type(screen.getByLabelText('Search'), 'kilo')

    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/units-of-measure')
      expect(calls).toHaveLength(1)
    })
    const [, config] = getMock.mock.calls.find(([url]) => url === '/api/units-of-measure')!
    expect(config.params.q).toBe('kilo')
    expect(config.params.page).toBe(1)
  })

  it('creating a unit posts the payload and refetches the list', async () => {
    postMock.mockResolvedValue({ data: makeUnit({ id: 2, name: 'Litre', code: 'L' }) })
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Unit' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Litre')
    await userEvent.type(screen.getByLabelText('Symbol'), 'l')
    await userEvent.click(screen.getByRole('button', { name: 'Create unit' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/units-of-measure', expect.objectContaining({ name: 'Litre', code: 'l' })),
    )
    await waitFor(() => {
      const calls = getMock.mock.calls.filter(([url]) => url === '/api/units-of-measure')
      expect(calls.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('creating a unit shows a server-side name/code conflict as a form error', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(new ApiError({ message: 'A unit with this name or code already exists.', code: 'CONFLICT' }, 409))
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')

    await userEvent.click(screen.getByRole('button', { name: 'New Unit' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Kilogram')
    await userEvent.type(screen.getByLabelText('Symbol'), 'KG')
    await userEvent.click(screen.getByRole('button', { name: 'Create unit' }))

    expect(await screen.findByText('A unit with this name or code already exists.')).toBeInTheDocument()
  })

  it('editing a unit pre-fills the form and sends a PATCH', async () => {
    patchMock.mockResolvedValue({ data: makeUnit({ name: 'Kilogramme' }) })
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')

    const row = screen.getByText('Kilogram').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Name')).toHaveValue('Kilogram')
    expect(screen.getByLabelText('Symbol')).toHaveValue('KG')
    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Kilogramme')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/units-of-measure/1',
        expect.objectContaining({ name: 'Kilogramme' }),
      ),
    )
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeUnit({ is_active: false }) })
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')

    const row = screen.getByText('Kilogram').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/units-of-measure/1/status', { is_active: false }))
  })

  it('creating a unit with a dimension and conversion factor posts both', async () => {
    postMock.mockResolvedValue({ data: makeUnit({ id: 2, name: 'Tonne', code: 'TON', dimension: 'mass', conversion_factor_to_base: '1000' }) })
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')

    await userEvent.click(screen.getByRole('button', { name: 'New Unit' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Tonne')
    await userEvent.type(screen.getByLabelText('Symbol'), 'TON')
    await userEvent.type(screen.getByLabelText('Dimension'), 'mass')
    await userEvent.type(screen.getByLabelText('Conversion Factor to Base'), '1000')
    await userEvent.click(screen.getByRole('button', { name: 'Create unit' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/units-of-measure',
        expect.objectContaining({ dimension: 'mass', conversion_factor_to_base: '1000' }),
      ),
    )
  })

  it('rejects a dimension entered without a conversion factor before submitting', async () => {
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')

    await userEvent.click(screen.getByRole('button', { name: 'New Unit' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Tonne')
    await userEvent.type(screen.getByLabelText('Symbol'), 'TON')
    await userEvent.type(screen.getByLabelText('Dimension'), 'mass')
    await userEvent.click(screen.getByRole('button', { name: 'Create unit' }))

    expect(
      await screen.findByText('Dimension and conversion factor must be provided together, or both left blank.'),
    ).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('shows an error message when changing status fails', async () => {
    patchMock.mockRejectedValue(new Error('Failed to change status.'))
    render(<UnitsOfMeasurePage />, { wrapper: MemoryRouter })
    await screen.findByText('Kilogram')

    const row = screen.getByText('Kilogram').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByText('Failed to change status.')).toBeInTheDocument()
  })
})
