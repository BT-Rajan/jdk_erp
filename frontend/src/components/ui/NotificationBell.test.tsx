import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationBell } from './NotificationBell'

const { getMock, patchMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  patchMock: vi.fn(),
  postMock: vi.fn(),
}))

vi.mock('@/lib/apiClient', () => ({
  apiClient: { get: getMock, patch: patchMock, post: postMock },
}))

const NOTIFICATIONS = [
  {
    id: 1,
    type: 'INFO' as const,
    title: 'Your role was changed',
    message: 'Your role is now manager.',
    entity_type: 'user',
    entity_id: 1,
    target_url: '/target-page',
    is_read: false,
    created_at: '2026-01-01T00:00:00',
    read_at: null,
  },
  {
    id: 2,
    type: 'SUCCESS' as const,
    title: 'Already read',
    message: 'This one was already read.',
    entity_type: null,
    entity_id: null,
    target_url: null,
    is_read: true,
    created_at: '2026-01-01T00:00:00',
    read_at: '2026-01-01T01:00:00',
  },
]

function renderBell() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<NotificationBell />} />
        <Route path="/target-page" element={<p>Target page content</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  getMock.mockReset()
  patchMock.mockReset().mockResolvedValue({})
  postMock.mockReset().mockResolvedValue({})
  getMock.mockImplementation((url: string) => {
    if (url === '/api/notifications/unread-count') return Promise.resolve({ data: { count: 1 } })
    if (url === '/api/notifications') return Promise.resolve({ data: NOTIFICATIONS })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

describe('NotificationBell', () => {
  it('shows the unread count from the initial poll', async () => {
    renderBell()
    expect(await screen.findByText('1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Notifications, 1 unread' })).toBeInTheDocument()
  })

  it('opens the panel and lists notifications on click', async () => {
    renderBell()
    await userEvent.click(await screen.findByRole('button', { name: /Notifications/ }))

    expect(await screen.findByText('Your role was changed')).toBeInTheDocument()
    expect(screen.getByText('Already read')).toBeInTheDocument()
  })

  it('marks an unread notification read and navigates to its target_url on click', async () => {
    renderBell()
    await userEvent.click(await screen.findByRole('button', { name: /Notifications/ }))
    await userEvent.click(await screen.findByText('Your role was changed'))

    expect(patchMock).toHaveBeenCalledWith('/api/notifications/1/read')
    expect(await screen.findByText('Target page content')).toBeInTheDocument()
  })

  it('does not re-mark an already-read notification, and does not navigate without a target_url', async () => {
    renderBell()
    await userEvent.click(await screen.findByRole('button', { name: /Notifications/ }))
    await userEvent.click(await screen.findByText('Already read'))

    expect(patchMock).not.toHaveBeenCalled()
    expect(screen.queryByText('Target page content')).not.toBeInTheDocument()
  })

  it('mark all read clears the unread badge and calls the endpoint', async () => {
    renderBell()
    await screen.findByText('1')
    await userEvent.click(screen.getByRole('button', { name: /Notifications/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Mark all read' }))

    expect(postMock).toHaveBeenCalledWith('/api/notifications/mark-all-read')
    await waitFor(() => expect(screen.queryByText('1')).not.toBeInTheDocument())
  })

  it('shows an empty state when there are no notifications', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/notifications/unread-count') return Promise.resolve({ data: { count: 0 } })
      if (url === '/api/notifications') return Promise.resolve({ data: [] })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    renderBell()
    await userEvent.click(await screen.findByRole('button', { name: 'Notifications' }))
    expect(await screen.findByText('No notifications yet.')).toBeInTheDocument()
  })
})
