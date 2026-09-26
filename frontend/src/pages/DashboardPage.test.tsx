import { render, screen, fireEvent } from '@testing-library/react'
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

  it('groups items into tabs by their existing type and filters the table on selection', async () => {
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
        {
          type: 'po_overdue',
          label: 'Overdue for delivery',
          entity: 'purchase_order',
          id: 13,
          reference: '2650005',
          supplier_name: 'Beta Supplies',
          detail: 'Overdue 1 day(s)',
          date: '2026-09-11',
        },
      ],
    })

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    )

    await screen.findByRole('link', { name: '2630003' })

    const allTab = screen.getByRole('tab', { name: /All\s*3/ })
    expect(allTab).toHaveAttribute('aria-selected', 'true')
    const overdueTab = screen.getByRole('tab', { name: /Overdue for delivery\s*2/ })

    fireEvent.click(overdueTab)

    expect(screen.queryByRole('link', { name: '2630003' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '2650004' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '2650005' })).toBeInTheDocument()
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
