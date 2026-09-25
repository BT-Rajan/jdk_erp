import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage } from './DashboardPage'

const { useAuthMock, getMock } = vi.hoisted(() => ({ useAuthMock: vi.fn(), getMock: vi.fn() }))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock } }
})

beforeEach(() => {
  getMock.mockReset()
  useAuthMock.mockReturnValue({ user: { id: 1, full_name: 'Ada Lovelace', role: 'admin' } })
})

describe('DashboardPage', () => {
  it('lists action items and links each one to its existing RFQ/PO screen', async () => {
    getMock.mockResolvedValue({
      data: [
        {
          type: 'rfq_needs_decision',
          label: 'Supplier response needs a decision',
          entity: 'rfq',
          id: 7,
          reference: '2630003',
          supplier_name: null,
          detail: '2/2 supplier(s) responded',
          date: '2026-09-01',
        },
        {
          type: 'po_overdue',
          label: 'Overdue for delivery',
          entity: 'purchase_order',
          id: 12,
          reference: '2650004',
          supplier_name: 'Acme Traders',
          detail: 'Overdue 3 day(s)',
          date: '2026-09-10',
        },
      ],
    })

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    )

    const rfqLink = await screen.findByRole('link', { name: '2630003' })
    expect(rfqLink).toHaveAttribute('href', '/rfqs/7')
    const poLink = screen.getByRole('link', { name: '2650004' })
    expect(poLink).toHaveAttribute('href', '/purchase-orders/12')
    expect(screen.getByText('Overdue 3 day(s)')).toBeInTheDocument()
    expect(screen.getByText('Acme Traders')).toBeInTheDocument()
  })

  it('shows an empty state once nothing needs attention', async () => {
    getMock.mockResolvedValue({ data: [] })

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Nothing needs your attention')).toBeInTheDocument()
  })
})
