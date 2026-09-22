import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { RequireAuth } from './RequireAuth'

const { useAuthMock } = vi.hoisted(() => ({ useAuthMock: vi.fn() }))
vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<p>Login page</p>} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <p>Protected content</p>
            </RequireAuth>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireAuth', () => {
  it('shows a loading state while the session check is in flight', () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: true })
    renderAt('/')
    expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
  })

  it('redirects to /login when loading has finished and there is no user', () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: false })
    renderAt('/')
    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('renders the protected content once a user is present', () => {
    useAuthMock.mockReturnValue({ user: { id: 1, full_name: 'Ada' }, isLoading: false })
    renderAt('/')
    expect(screen.getByText('Protected content')).toBeInTheDocument()
  })
})
