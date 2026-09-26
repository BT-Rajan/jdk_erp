import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QuotationDetailPage } from './QuotationDetailPage'

const { useAuthMock, getMock, postMock, putMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  getMock: vi.fn(),
  postMock: vi.fn(),
  putMock: vi.fn(),
}))

vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))
vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, put: putMock } }
})

const EMPTY_PAGE = { data: [], pagination: { page: 1, page_size: 200, total: 0, total_pages: 1 } }

function makeQuotation(status: string) {
  return {
    id: 9,
    quotation_number: '2640001',
    customer_id: 3,
    customer_name: 'A Co',
    created_by_user_id: 2,
    created_by_name: 'Salesman',
    quotation_date: '2026-09-28',
    requested_delivery_date: '2026-10-05',
    status,
    currency: 'KWD',
    subtotal_amount: '360.000',
    total_amount: '360.000',
    price_approval_required: true,
    price_decision: null,
    price_decision_reason: null,
    price_decision_at: null,
    delivery_window: 'more_than_2_working_days',
    readiness_status: 'commercial_approval_required',
    can_edit: false,
    valid_until: '2026-10-05',
    accepted_at: '2026-09-28T06:00:00',
    rejected_at: null,
    rejection_reason: null,
    is_expired: false,
    order_eligible: status === 'accepted',
    can_accept: false,
    can_reject: false,
    can_renew: false,
    can_convert: false,
    sales_order_id: status === 'converted' ? 5 : null,
    created_at: '2026-09-28T06:00:00',
    updated_at: '2026-09-28T06:00:00',
    lines: [
      {
        id: 1,
        line_number: 1,
        product_id: 7,
        quantity: '3',
        unit_of_measure_id: 2,
        unit_price: '120',
        line_amount: '360.000',
        min_selling_price: '90',
        max_selling_price: '110',
        price_approval_required: true,
      },
    ],
  }
}

const READINESS = {
  status: 'commercial_approval_required',
  delivery_window: 'more_than_2_working_days',
  conditions: ['commercial_approval_required'],
  reason_codes: ['price_outside_range'],
  feasibility_check_id: null,
  feasibility_state: null,
  commercial_approval_required: true,
}

function setup(status: string) {
  getMock.mockImplementation((url: string) => {
    if (url === '/api/quotations/9') return Promise.resolve({ data: makeQuotation(status) })
    if (url === '/api/quotations/9/feasibility-checks') return Promise.resolve({ data: [] })
    return Promise.resolve({ data: EMPTY_PAGE })
  })
  postMock.mockResolvedValue({ data: READINESS })
  render(
    <MemoryRouter initialEntries={['/sales/quotations/9']}>
      <Routes>
        <Route path="/sales/quotations/:quotationId" element={<QuotationDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useAuthMock.mockReset().mockReturnValue({ user: { id: 1, full_name: 'Admin', role: 'admin' } })
  getMock.mockReset()
  postMock.mockReset()
  putMock.mockReset()
})

describe('QuotationDetailPage price decision (S16.1)', () => {
  it('offers Admin the price decision on an unconverted quotation', async () => {
    setup('accepted')
    expect(await screen.findByRole('button', { name: 'Approve Prices' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject Prices' })).toBeInTheDocument()
  })

  it('shows no price decision actions once the quotation is converted', async () => {
    setup('converted')
    expect(await screen.findByText(/this quotation is locked/i)).toBeInTheDocument()
    expect(screen.getByText('Price Approval')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve Prices' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject Prices' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/price decision reason/i)).not.toBeInTheDocument()
    await waitFor(() => expect(postMock).not.toHaveBeenCalled())
  })
})
