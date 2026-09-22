import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OrganisationSettingsPage } from './OrganisationSettingsPage'

const { useAuthMock, getMock, patchMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  patchMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, patch: patchMock } }
})

const ADMIN = { id: 1, full_name: 'Admin User', role: 'admin' }

function makeOrganisation(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    name: 'JDK Trading Co',
    code: 'JDK',
    contact_email: 'ops@jdk.example',
    contact_phone: '+965 1234 5678',
    address: '123 Industrial Ave',
    email_domain: 'jdk.example',
    currency: 'KWD',
    timezone: 'Asia/Kuwait',
    is_active: true,
    ...overrides,
  }
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: ADMIN })
  getMock.mockReset()
  patchMock.mockReset()
  getMock.mockResolvedValue({ data: makeOrganisation() })
})

describe('OrganisationSettingsPage', () => {
  it('shows AccessDeniedState for a non-admin instead of the form', () => {
    useAuthMock.mockReturnValue({ user: { id: 2, full_name: 'Team Member', role: 'team_member' } })
    render(<OrganisationSettingsPage />)

    expect(screen.getByText('Access denied')).toBeInTheDocument()
    expect(getMock).not.toHaveBeenCalled()
  })

  it('loads and renders the organisation details on mount', async () => {
    render(<OrganisationSettingsPage />)

    expect(await screen.findByDisplayValue('JDK Trading Co')).toBeInTheDocument()
    expect(screen.getByDisplayValue('JDK')).toBeInTheDocument()
    expect(screen.getByDisplayValue('KWD')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('shows an error state when loading fails', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    getMock.mockRejectedValue(new ApiError({ message: 'Network down', code: 'SERVER_ERROR' }, 500))
    render(<OrganisationSettingsPage />)

    expect(await screen.findByText('Network down')).toBeInTheDocument()
  })

  it('saving edits sends the updated fields and re-renders with the response', async () => {
    patchMock.mockResolvedValue({ data: makeOrganisation({ name: 'Renamed Org' }) })
    render(<OrganisationSettingsPage />)
    await screen.findByDisplayValue('JDK Trading Co')

    const nameField = screen.getByLabelText('Name')
    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Renamed Org')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(
        '/api/organisations/me',
        expect.objectContaining({ name: 'Renamed Org', code: 'JDK', currency: 'KWD' }),
      ),
    )
    expect(await screen.findByDisplayValue('Renamed Org')).toBeInTheDocument()
  })

  it('shows a field-level error when the server rejects a duplicate code', async () => {
    const { ApiError } = await import('@/lib/apiClient')
    patchMock.mockRejectedValue(new ApiError({ message: 'This action conflicts with existing data.', code: 'CONFLICT' }, 409))
    render(<OrganisationSettingsPage />)
    await screen.findByDisplayValue('JDK Trading Co')

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('This action conflicts with existing data.')).toBeInTheDocument()
  })

  it('deactivating asks for confirmation, then calls the status endpoint and updates the badge', async () => {
    patchMock.mockResolvedValue({ data: makeOrganisation({ is_active: false }) })
    render(<OrganisationSettingsPage />)
    await screen.findByDisplayValue('JDK Trading Co')

    await userEvent.click(screen.getByRole('button', { name: 'Deactivate organisation' }))
    expect(screen.getByText(/Every user in this organisation, including you, will be signed out/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/organisations/me/status', { is_active: false }),
    )
    expect(await screen.findByText('Inactive')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Activate organisation' })).toBeInTheDocument()
  })

  it('shows an error message when changing status fails', async () => {
    patchMock.mockRejectedValue(new Error('Failed to change organisation status.'))
    render(<OrganisationSettingsPage />)
    await screen.findByDisplayValue('JDK Trading Co')

    await userEvent.click(screen.getByRole('button', { name: 'Deactivate organisation' }))
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByText('Failed to change organisation status.')).toBeInTheDocument()
  })
})
