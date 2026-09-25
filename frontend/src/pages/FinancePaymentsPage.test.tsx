import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FinancePaymentsPage } from './FinancePaymentsPage'

const { getMock, postMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock } }
})

const PO = {
  id: 7,
  po_number: '2650001',
  supplier_name: 'Acme Traders',
  order_date: '2026-09-01',
  expected_delivery_date: '2026-09-30',
  payment_terms: 'Prepaid',
  supplier_reference: null,
  rfq_number: null,
  notes: null,
  status: 'approved',
  approved_at: '2026-09-02T08:00:00',
  currency: 'KWD',
  final_amount: '1000.0000',
  paid_amount: '0',
  outstanding_amount: '1000.0000',
  refundable_amount: '0.0000',
  payment_status: 'unpaid',
  lines: [{ material_name: 'Cement', quantity: '10.0000', unit_code: 'BAG', unit_price: '100.0000', line_total: '1000.0000' }],
  payments: [],
}

beforeEach(() => {
  getMock.mockReset()
  postMock.mockReset()
  getMock.mockImplementation((url: string) =>
    url === '/api/finance/purchase-orders'
      ? Promise.resolve({ data: { data: [PO], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 } } })
      : Promise.resolve({ data: { ...PO, paid_amount: '1000.0000', outstanding_amount: '0.0000', payment_status: 'paid' } }),
  )
  postMock.mockResolvedValue({ data: {} })
})

describe('FinancePaymentsPage', () => {
  it('opens an approved PO read-only and records only amount, date, mode and notes', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/finance/payments']}>
        <Routes>
          <Route path="/finance/payments" element={<FinancePaymentsPage />} />
          <Route path="/finance/payments/:purchaseOrderId" element={<FinancePaymentsPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Prepaid')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open' }))
    const view = await screen.findByRole('region', { name: 'Payment for 2650001' })
    expect(within(view).getByText(/record the payment already made/)).toBeInTheDocument()
    // The PO itself is not editable -- only the payment fields are inputs.
    expect(within(view).getAllByRole('textbox')).toHaveLength(1)

    await user.selectOptions(within(view).getByLabelText(/Payment Mode/), 'Bank Transfer')
    await user.type(within(view).getByLabelText('Notes'), 'Paid on 1 Sep')
    await user.click(within(view).getByRole('button', { name: 'Save Payment' }))

    expect(postMock).toHaveBeenCalledWith('/api/purchase-orders/7/payments', {
      amount: '1000',
      payment_date: expect.any(String),
      payment_method: 'Bank Transfer',
      notes: 'Paid on 1 Sep',
    })
    expect(await within(view).findByText(/Payment of 1,000.000 KWD recorded/)).toBeInTheDocument()
  })
})
