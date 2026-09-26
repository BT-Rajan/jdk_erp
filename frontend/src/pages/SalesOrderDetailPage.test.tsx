import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { SalesOrderDetailPage } from './SalesOrderDetailPage'

const { getMock, postMock, patchMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
}))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})

const EMPTY_PAGE = { data: [], pagination: { page: 1, page_size: 200, total: 0, total_pages: 1 } }

const ORDER = {
  id: 5,
  order_number: '2660001',
  quotation_id: 9,
  quotation_number: '2640001',
  customer_id: 3,
  customer_name: 'A Co',
  order_date: '2026-09-28',
  requested_delivery_date: '2026-10-05',
  currency: 'KWD',
  subtotal_amount: '300.000',
  total_amount: '300.000',
  status: 'open',
  cancellation_reason: null,
  cancelled_at: null,
  updated_at: '2026-09-28T06:00:00',
  lines: [{ id: 1, line_number: 1, product_id: 7, quantity: '3', unit_of_measure_id: 2, unit_price: '100', line_amount: '300.000' }],
  can_cancel: false,
  can_edit: true,
}

beforeEach(() => {
  getMock.mockReset().mockImplementation((url: string) => {
    if (url === '/api/sales-orders/5') return Promise.resolve({ data: ORDER })
    return Promise.resolve({ data: EMPTY_PAGE })
  })
  postMock.mockReset()
  patchMock.mockReset().mockResolvedValue({ data: ORDER })
})

describe('SalesOrderDetailPage', () => {
  it('never offers or sends a customer change in the Admin edit (S13.5)', async () => {
    render(
      <MemoryRouter initialEntries={['/sales/orders/5']}>
        <Routes>
          <Route path="/sales/orders/:orderId" element={<SalesOrderDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Edit (Admin)' }))

    expect(screen.queryByLabelText(/customer/i)).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/reason for the change/i), 'Customer asked for a later date')
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1))
    const [url, body] = patchMock.mock.calls[0]
    expect(url).toBe('/api/sales-orders/5')
    expect(body).not.toHaveProperty('customer_id')
  })
})
