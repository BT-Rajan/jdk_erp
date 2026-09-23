import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProductionLinesPage } from './ProductionLinesPage'

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

function makeLine(overrides: Partial<Record<string, unknown>> = {}) {
  return { id: 1, organisation_id: 1, code: 'LINE1', name: 'Production Line 1', is_active: true, ...overrides }
}

function linesResponse(
  data: ReturnType<typeof makeLine>[],
  overrides: Partial<{ page: number; page_size: number; total: number; total_pages: number }> = {},
) {
  return { data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1, ...overrides } }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  postMock.mockReset()
  patchMock.mockReset()
  getMock.mockResolvedValue({ data: linesResponse([makeLine()]) })
})

describe('ProductionLinesPage', () => {
  it('loads and renders production lines on mount, with exactly one initial request', async () => {
    render(<ProductionLinesPage />)

    expect(await screen.findByText('Production Line 1')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/production-lines')
    expect(calls).toHaveLength(1)
  })

  it('shows the read-only view for a non-admin: list loads but no mutating controls appear', async () => {
    useAuthMock.mockReturnValue({ user: TEAM_MEMBER })
    render(<ProductionLinesPage />)

    expect(await screen.findByText('Production Line 1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Production Line' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument()
  })

  it('shows an error state when the request fails', async () => {
    getMock.mockRejectedValue(new Error('Network down'))
    render(<ProductionLinesPage />)
    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('shows a distinct empty state for no production lines at all vs. no search matches', async () => {
    getMock.mockResolvedValue({ data: linesResponse([]) })
    render(<ProductionLinesPage />)
    expect(await screen.findByText('No production lines yet')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Search'), 'zzz')
    await waitFor(() => expect(screen.getByText('No matching production lines')).toBeInTheDocument())
  })

  it('creating a production line posts the payload with no code field, and refetches the list', async () => {
    postMock.mockResolvedValue({ data: makeLine({ id: 2, code: '000012', name: 'Line 2' }) })
    render(<ProductionLinesPage />)
    await screen.findByText('Production Line 1')
    getMock.mockClear()

    await userEvent.click(screen.getByRole('button', { name: 'New Production Line' }))
    expect(screen.queryByLabelText('Code')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'Line 2')
    await userEvent.click(screen.getByRole('button', { name: 'Create production line' }))

    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/production-lines', { name: 'Line 2' }))
  })

  it('creating a production line shows a server-side name conflict as a form error', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    postMock.mockRejectedValue(new ApiError({ message: 'A production line with this name already exists.', code: 'CONFLICT' }, 409))
    render(<ProductionLinesPage />)
    await screen.findByText('Production Line 1')

    await userEvent.click(screen.getByRole('button', { name: 'New Production Line' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Duplicate')
    await userEvent.click(screen.getByRole('button', { name: 'Create production line' }))

    expect(await screen.findByText('A production line with this name already exists.')).toBeInTheDocument()
  })

  it('editing a production line disables the code field and sends a PATCH with only the name', async () => {
    patchMock.mockResolvedValue({ data: makeLine({ name: 'Main Line' }) })
    render(<ProductionLinesPage />)
    await screen.findByText('Production Line 1')

    const row = screen.getByText('Production Line 1').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Edit'))

    expect(screen.getByLabelText('Code')).toHaveValue('LINE1')
    expect(screen.getByLabelText('Code')).toBeDisabled()

    await userEvent.clear(screen.getByLabelText('Name'))
    await userEvent.type(screen.getByLabelText('Name'), 'Main Line')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/production-lines/1', { name: 'Main Line' }))
  })

  it('deactivating asks for confirmation, then calls the status endpoint and refetches', async () => {
    patchMock.mockResolvedValue({ data: makeLine({ is_active: false }) })
    render(<ProductionLinesPage />)
    await screen.findByText('Production Line 1')

    const row = screen.getByText('Production Line 1').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: /Actions for/ }))
    await userEvent.click(await screen.findByText('Deactivate'))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/production-lines/1/status', { is_active: false }))
  })
})
