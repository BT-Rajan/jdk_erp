import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import { getStoredTokens, setStoredTokens } from './tokenStorage'

const { getMock, postMock, setOnSessionExpiredMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  setOnSessionExpiredMock: vi.fn(),
}))

vi.mock('@/lib/apiClient', () => ({
  apiClient: { get: getMock, post: postMock },
  setOnSessionExpired: setOnSessionExpiredMock,
}))

const USER = {
  id: 1,
  organisation_id: 1,
  full_name: 'Ada Lovelace',
  email: 'ada@example.com',
  username: 'ada',
  is_active: true,
  last_login_at: null,
  role: 'admin',
  team_ids: [],
}

function Probe() {
  const { user, isLoading, login, logout } = useAuth()
  return (
    <div>
      <p>{isLoading ? 'loading' : 'ready'}</p>
      <p>{user ? user.full_name : 'signed out'}</p>
      <button onClick={() => login('ada', 'correct-horse')}>Sign in</button>
      <button onClick={() => logout()}>Sign out</button>
    </div>
  )
}

beforeEach(() => {
  localStorage.clear()
  getMock.mockReset()
  postMock.mockReset()
  setOnSessionExpiredMock.mockReset()
})

describe('AuthProvider', () => {
  it('starts signed out, without calling /me, when no tokens are stored', async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    await waitFor(() => expect(screen.getByText('ready')).toBeInTheDocument())
    expect(screen.getByText('signed out')).toBeInTheDocument()
    expect(getMock).not.toHaveBeenCalled()
  })

  it('rehydrates the current user from /api/auth/me when tokens are already stored', async () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    getMock.mockResolvedValue({ data: USER })

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    await waitFor(() => expect(screen.getByText('Ada Lovelace')).toBeInTheDocument())
    expect(getMock).toHaveBeenCalledWith('/api/auth/me')
  })

  it('logs in, stores the returned tokens, and loads the user', async () => {
    postMock.mockResolvedValue({ data: { access_token: 'a', refresh_token: 'r', token_type: 'bearer' } })
    getMock.mockResolvedValue({ data: USER })

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('ready')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByText('Ada Lovelace')).toBeInTheDocument())
    expect(postMock).toHaveBeenCalledWith('/api/auth/login', { username: 'ada', password: 'correct-horse' })
    expect(getStoredTokens()).toEqual({ accessToken: 'a', refreshToken: 'r' })
  })

  it('logs out, clears stored tokens, and signs the user out even if the server call fails', async () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    getMock.mockResolvedValue({ data: USER })
    postMock.mockRejectedValue(new Error('network down'))

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('Ada Lovelace')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument())
    expect(getStoredTokens()).toBeNull()
  })

  it('registers a session-expiry handler that signs the user out', async () => {
    setStoredTokens({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    getMock.mockResolvedValue({ data: USER })

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('Ada Lovelace')).toBeInTheDocument())

    const handler = setOnSessionExpiredMock.mock.calls[0][0] as () => void
    act(() => handler())

    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument())
  })
})
