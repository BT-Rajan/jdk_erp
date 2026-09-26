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
  status: 'handed_off',
  cancellation_reason: null,
  cancelled_at: null,
  handed_off_at: '2026-09-28T06:00:00',
  handoff_source: 'automatic',
  updated_at: '2026-09-28T06:00:00',
  lines: [{ id: 1, line_number: 1, product_id: 7, quantity: '3', unit_of_measure_id: 2, unit_price: '100', line_amount: '300.000' }],
  can_cancel: false,
  can_edit: true,
}

/** Line 1 already assessed for fulfilment at hand-off (S15.2). */
let fulfilment: { sales_order_line_id: number }[] = [{ sales_order_line_id: 1 }]

beforeEach(() => {
  fulfilment = [{ sales_order_line_id: 1 }]
  getMock.mockReset().mockImplementation((url: string) => {
    if (url === '/api/sales-orders/5') return Promise.resolve({ data: ORDER })
    if (url === '/api/sales-orders/5/fulfilment') return Promise.resolve({ data: fulfilment })
    return Promise.resolve({ data: EMPTY_PAGE })
  })
  postMock.mockReset()
  patchMock.mockReset().mockResolvedValue({ data: ORDER })
})

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/sales/orders/5']}>
      <Routes>
        <Route path="/sales/orders/:orderId" element={<SalesOrderDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SalesOrderDetailPage', () => {
  it('never offers or sends a customer change in the Admin edit (S13.5)', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit (Admin)' }))

    expect(screen.queryByLabelText(/customer/i)).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/reason for the change/i), 'Customer asked for a later date')
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1))
    const [url, body] = patchMock.mock.calls[0]
    expect(url).toBe('/api/sales-orders/5')
    expect(body).not.toHaveProperty('customer_id')
  })

  it('shows an assessed line quantity read-only while the price stays editable (S16.1)', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit (Admin)' }))

    expect(screen.queryByRole('spinbutton', { name: 'Line 1 quantity' })).not.toBeInTheDocument()
    expect(await screen.findByLabelText('Line 1 quantity (read-only)')).toHaveTextContent('3')
    expect(screen.getByText('Fixed: already assessed for fulfilment.')).toBeInTheDocument()
    await userEvent.clear(screen.getByRole('spinbutton', { name: 'Line 1 unit price' }))
    await userEvent.type(screen.getByRole('spinbutton', { name: 'Line 1 unit price' }), '95')
    await userEvent.type(screen.getByLabelText(/reason for the change/i), 'Agreed discount')
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1))
    expect(patchMock.mock.calls[0][1].lines).toEqual([{ product_id: 7, unit_of_measure_id: 2, quantity: '3', unit_price: '95' }])
  })

  it('keeps quantity editable on a line that was never assessed', async () => {
    fulfilment = []
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit (Admin)' }))

    const quantity = await screen.findByRole('spinbutton', { name: 'Line 1 quantity' })
    await userEvent.clear(quantity)
    await userEvent.type(quantity, '5')
    await userEvent.type(screen.getByLabelText(/reason for the change/i), 'Customer asked for 5')
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1))
    expect(patchMock.mock.calls[0][1].lines[0].quantity).toBe('5')
  })

  it('offers the Order Confirmation PDF only when the server reports one', async () => {
    renderPage()
    await screen.findByRole('button', { name: 'Edit (Admin)' })
    expect(screen.queryByRole('button', { name: 'Order Confirmation PDF' })).not.toBeInTheDocument()
  })

  it('downloads the Order Confirmation through the files endpoint', async () => {
    const withPdf = { ...ORDER, pdf_file: { id: 42, original_filename: 'Order-Confirmation-2660001.pdf' } }
    Object.assign(window.URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    getMock.mockImplementation((url: string) => {
      if (url === '/api/sales-orders/5') return Promise.resolve({ data: withPdf })
      if (url === '/api/files/42') return Promise.resolve({ data: new Blob(['%PDF']) })
      if (url === '/api/sales-orders/5/fulfilment') return Promise.resolve({ data: fulfilment })
      return Promise.resolve({ data: EMPTY_PAGE })
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Order Confirmation PDF' }))
    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(getMock).toHaveBeenCalledWith('/api/files/42', { responseType: 'blob' })
    click.mockRestore()
  })
})

