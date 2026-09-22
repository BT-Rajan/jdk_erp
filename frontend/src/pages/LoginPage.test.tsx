import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/apiClient'
import { LoginPage } from './LoginPage'

const { loginMock } = vi.hoisted(() => ({ loginMock: vi.fn() }))
vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: () => ({ login: loginMock }) }))

function renderLoginPage(initialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>Dashboard</p>} />
        <Route path="/suppliers" element={<p>Suppliers page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  loginMock.mockReset()
})

describe('LoginPage', () => {
  it('requires both fields before submitting', async () => {
    renderLoginPage()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Username is required')).toBeInTheDocument()
    expect(screen.getByText('Password is required')).toBeInTheDocument()
    expect(loginMock).not.toHaveBeenCalled()
  })

  it('shows the backend error message on failed login without redirecting', async () => {
    loginMock.mockRejectedValue(new ApiError({ code: 'AUTHENTICATION_ERROR', message: 'Invalid username or password.' }, 401))
    renderLoginPage()

    await userEvent.type(screen.getByLabelText('Username'), 'ada')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid username or password.')).toBeInTheDocument()
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument()
  })

  it('redirects to / on successful login by default', async () => {
    loginMock.mockResolvedValue(undefined)
    renderLoginPage()

    await userEvent.type(screen.getByLabelText('Username'), 'ada')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByText('Dashboard')).toBeInTheDocument())
    expect(loginMock).toHaveBeenCalledWith('ada', 'correct-horse')
  })

  it('redirects back to the page that triggered the login, when RequireAuth provided one', async () => {
    loginMock.mockResolvedValue(undefined)
    render(
      <MemoryRouter
        initialEntries={[{ pathname: '/login', state: { from: { pathname: '/suppliers' } } }]}
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/suppliers" element={<p>Suppliers page</p>} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.type(screen.getByLabelText('Username'), 'ada')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByText('Suppliers page')).toBeInTheDocument())
  })
})
