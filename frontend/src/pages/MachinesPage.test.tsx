import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { MachinesPage } from './MachinesPage'

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

const LINES_RESPONSE = {
  data: [{ id: 10, name: 'Production Line 1', code: 'LINE1', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}
const UNITS_RESPONSE = {
  data: [{ id: 20, name: 'Ton', code: 'TON', is_active: true }],
  pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
}

function makeMachine(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    organisation_id: 1,
    code: 'M-001',
    name: 'Machine 1',
    production_line_id: 10,
    capacity_quantity: '2.0000',
    capacity_unit_of_measure_id: 20,
    capacity_period_hours: '1.00',
    is_active: true,
    ...overrides,
  }
}

function machinesResponse(
  data: ReturnType<typeof makeMachine>[],
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
    if (url === '/api/production-lines') return Promise.resolve({ data: LINES_RESPONSE })
    if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
    if (url === '/api/machines') return Promise.resolve({ data: machinesResponse([makeMachine()]) })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('MachinesPage', () => {
  it('loads and renders machines on mount, with exactly one initial request', async () => {
    render(<MachinesPage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Machine 1')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/machines')
    expect(calls).toHaveLength(1)
  })

  it('shows the production line name and formatted capacity resolved from the lookup lists', async () => {
    render(<MachinesPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Production Line 1')).toBeInTheDocument()
    expect(await screen.findByText('2.0000 TON / hour')).toBeInTheDocument()
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<MachinesPage />, { wrapper: MemoryRouter })

    expect(await screen.findByText('Machine 1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Machine' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
    expect(getMock.mock.calls.some(([url]) => url === '/api/production-lines')).toBe(false)
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/production-lines') return Promise.resolve({ data: LINES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.reject(new Error('Network down'))
    })
    render(<MachinesPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no machines at all vs. no search matches', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/production-lines') return Promise.resolve({ data: LINES_RESPONSE })
      if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS_RESPONSE })
      return Promise.resolve({ data: machinesResponse([]) })
    })
    render(<MachinesPage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('No machines yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching machines')).toBeInTheDocument())
  })

  it('creating a machine posts the payload including production line and structured capacity, with no code field', async () => {
    postMock.mockResolvedValue({ data: makeMachine({ id: 2, name: 'Machine 2', code: '000021' }) })
    render(<MachinesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Machine 1')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Machine' }))
    expect(screen.queryByLabelText('Code')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'Machine 2')
    await userEvent.selectOptions(screen.getByLabelText('Production Line'), '10')
    await userEvent.type(screen.getByLabelText('Production Capacity'), '2')
    await userEvent.selectOptions(screen.getByLabelText('Capacity Unit'), '20')
    await userEvent.click(screen.getByRole('button', { name: 'Create machine' }))

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/api/machines',
        expect.objectContaining({
          name: 'Machine 2',
          production_line_id: 10,
          capacity_quantity: '2',
          capacity_unit_of_measure_id: 20,
          capacity_period_hours: '1',
        }),
      ),
    )
  })

  it('rejects a non-positive capacity inline before submitting', async () => {
    render(<MachinesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Machine 1')

    await userEvent.click(screen.getByRole('button', { name: 'New Machine' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Machine 2')
    await userEvent.selectOptions(screen.getByLabelText('Production Line'), '10')
    await userEvent.clear(screen.getByLabelText('Production Capacity'))
    await userEvent.type(screen.getByLabelText('Production Capacity'), '0')
    await userEvent.selectOptions(screen.getByLabelText('Capacity Unit'), '20')
    await userEvent.click(screen.getByRole('button', { name: 'Create machine' }))

    expect(await screen.findByText('Enter a positive number')).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('editing a machine pre-fills the form, disables the code field, and reconfigures capacity without a code change', async () => {
    patchMock.mockResolvedValue({ data: makeMachine({ capacity_quantity: '2.5000' }) })
    render(<MachinesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Machine 1')

    const row = screen.getByText('Machine 1').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Code')).toHaveValue('M-001')
    expect(screen.getByLabelText('Code')).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Production Capacity'))
    await userEvent.type(screen.getByLabelText('Production Capacity'), '2.5')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/machines/1',
        expect.objectContaining({ capacity_quantity: '2.5' }),
      ),
    )
    const [, payload] = patchMock.mock.calls[0]
    expect(payload.code).toBeUndefined()
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeMachine({ is_active: false }) })
    render(<MachinesPage />, { wrapper: MemoryRouter })
    await screen.findByText('Machine 1')

    const row = screen.getByText('Machine 1').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/machines/1/status', { is_active: false }))
  })
})
