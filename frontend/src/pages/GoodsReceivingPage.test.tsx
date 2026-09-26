import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GoodsReceivingPage } from './GoodsReceivingPage'

const { getMock, postMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock } }
})

/** Ordered 1000, previously received 600, remaining 400 -- the task's own
 * worked example for making a partial receipt obvious. */
function po(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 42,
    po_number: '2650007',
    supplier_name: 'Acme Traders',
    warehouse_name: 'Main Warehouse',
    expected_delivery_date: '2026-10-01',
    delivery_instructions: null,
    status: 'partially_received',
    can_receive: true,
    lines: [
      {
        id: 501,
        raw_material_id: 9,
        material_name: 'Gypsum',
        unit_code: 'KG',
        ordered_quantity: '1000.0000',
        received_quantity: '600.0000',
        remaining_quantity: '400.0000',
      },
    ],
    receipts: [],
    ...overrides,
  }
}

const LIST_RESPONSE = { data: [po()], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 } }

beforeEach(() => {
  getMock.mockReset()
  postMock.mockReset()
  getMock.mockImplementation((url: string) => {
    if (url === '/api/goods-receiving') return Promise.resolve({ data: LIST_RESPONSE })
    return Promise.reject(new Error(`Unexpected GET ${url}`))
  })
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/goods-receiving']}>
      <GoodsReceivingPage />
    </MemoryRouter>,
  )
}

describe('GoodsReceivingPage', () => {
  it('shows ordered/received/remaining and status on the receivable-PO list without opening it', async () => {
    renderPage()

    expect(await screen.findByText('2650007')).toBeInTheDocument()
    expect(screen.getByText('Acme Traders')).toBeInTheDocument()
    expect(screen.getByText('Gypsum')).toBeInTheDocument()
    // Ordered/received/remaining, straight from the line data -- no extra click needed.
    expect(screen.getByText(/600\/1,000 KG/)).toBeInTheDocument()
    expect(screen.getByText(/400 remaining/)).toBeInTheDocument()
    expect(screen.getByText('Partially Received')).toBeInTheDocument()
  })

  it('shows Ordered / Previously Received / Remaining / UOM as separate columns, remaining pre-filled', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Actions for 2650007/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Receive Goods...' }))

    const dialog = await screen.findByRole('dialog')
    const headers = within(dialog).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(
      expect.arrayContaining(['Material', 'Ordered', 'Previously Received', 'Remaining', 'UOM', 'Received Now', 'Remarks']),
    )

    const row = within(dialog).getByText('Gypsum').closest('tr')!
    expect(within(row).getByText('1,000')).toBeInTheDocument() // Ordered
    expect(within(row).getByText('600')).toBeInTheDocument() // Previously Received
    expect(within(row).getByText('400')).toBeInTheDocument() // Remaining, called out explicitly
    expect(within(row).getByText('KG')).toBeInTheDocument() // UOM, its own column

    // The Received Now input defaults to the remaining quantity.
    const input = within(row).getByRole('spinbutton', { name: 'Received quantity for Gypsum' })
    expect(input).toHaveValue(400)
  })

  it('submits a partial receipt and reflects the updated received/remaining afterwards', async () => {
    const user = userEvent.setup()
    postMock.mockResolvedValue({
      data: po({
        lines: [
          {
            id: 501,
            raw_material_id: 9,
            material_name: 'Gypsum',
            unit_code: 'KG',
            ordered_quantity: '1000.0000',
            received_quantity: '850.0000',
            remaining_quantity: '150.0000',
          },
        ],
        receipts: [
          {
            id: 1,
            receipt_number: '26R0001',
            receipt_date: '2026-09-26',
            status: 'posted',
            posted_at: '2026-09-26T10:00:00',
            received_by_name: 'Warehouse User',
            supplier_delivery_reference: null,
            notes: null,
            days_late: 0,
            lines: [{ material_name: 'Gypsum', unit_code: 'KG', quantity: '250.0000', remarks: null }],
            documents: [],
          },
        ],
      }),
    })

    renderPage()
    await user.click(await screen.findByRole('button', { name: /Actions for 2650007/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Receive Goods...' }))

    const dialog = await screen.findByRole('dialog')
    const input = within(dialog).getByRole('spinbutton', { name: 'Received quantity for Gypsum' })
    await user.clear(input)
    await user.type(input, '250')

    await user.click(within(dialog).getByRole('button', { name: 'Submit Receipt' }))

    // The user only ever typed the quantity that arrived -- everything
    // else (PO, material, UOM) comes from the existing PO, never retyped.
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/goods-receiving/42/receipts', {
        receipt_date: expect.any(String),
        supplier_delivery_reference: null,
        notes: null,
        lines: [{ purchase_order_line_id: 501, quantity: '250', remarks: null }],
        file_ids: [],
      }),
    )

    // After submission: what was received, and what's left, are both
    // immediately visible -- no re-navigation required.
    expect(await within(dialog).findByText('26R0001')).toBeInTheDocument()
    expect(within(dialog).getByText(/Gypsum: 250 KG/)).toBeInTheDocument()
    const updatedRow = within(dialog).getByText('Gypsum').closest('tr')!
    expect(within(updatedRow).getByText('850')).toBeInTheDocument()
    expect(within(updatedRow).getByText('150')).toBeInTheDocument()
  })

  it('hides entry controls and shows the PO status when the PO is not open for receiving', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/api/goods-receiving')
        return Promise.resolve({
          data: { data: [po({ status: 'reconciliation_required', can_receive: false })], pagination: LIST_RESPONSE.pagination },
        })
      return Promise.reject(new Error(`Unexpected GET ${url}`))
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Actions for 2650007/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Receive Goods...' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Reconciliation Required')).toBeInTheDocument()
    expect(within(dialog).queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Submit Receipt' })).not.toBeInTheDocument()
  })
})
