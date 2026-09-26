import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssistantSettingsPage } from './AssistantSettingsPage'

const { useAuthMock, getMock, putMock } = vi.hoisted(() => ({ useAuthMock: vi.fn(), getMock: vi.fn(), putMock: vi.fn() }))
vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, put: putMock } }
})

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: { id: 1, full_name: 'Admin', role: 'admin' } })
  getMock.mockReset().mockResolvedValue({ data: { configured: false, provider: null, key_hint: null } })
  putMock.mockReset().mockResolvedValue({ data: { configured: true, provider: 'claude', key_hint: '...1234' } })
})

describe('AssistantSettingsPage', () => {
  it('lets an Admin save a key and shows only the provider and last four characters', async () => {
    render(<AssistantSettingsPage />)
    expect(await screen.findByText(/Not set/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('API key'), 'sk-ant-secret-1234')
    await userEvent.click(screen.getByRole('button', { name: 'Save Key' }))

    expect(putMock).toHaveBeenCalledWith('/api/assistant/settings', { api_key: 'sk-ant-secret-1234' })
    expect(await screen.findByText('Active: Claude (Anthropic), key ending ...1234.')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('sk-ant-secret-1234')).not.toBeInTheDocument()
  })

  it('is not available to non-admins', () => {
    useAuthMock.mockReturnValue({ user: { id: 2, full_name: 'Sam', role: 'team_member' } })
    render(<AssistantSettingsPage />)
    expect(getMock).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Save Key' })).not.toBeInTheDocument()
  })
})
