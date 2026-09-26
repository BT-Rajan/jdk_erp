import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ApiError } from '@/lib/apiClient'
import { DeliveriesPage } from './DeliveriesPage'
import { DeliveryInstructionPage } from './DeliveryInstructionPage'
import { DeliveryOrderPage } from './DeliveryOrderPage'
import type { DeliveryInstruction } from './deliveryShared'

const { getMock, postMock, patchMock, useAuthMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
  useAuthMock: vi.fn(),
}))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})
vi.mock('@/lib/auth/AuthContext', () => ({ useAuth: useAuthMock }))

const page = <T,>(data: T[]) => ({ data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1 } })

const PRODUCTS = page([{ id: 7, name: 'Widget', code: 'WID', is_active: true }])
const UNITS = page([{ id: 2, name: 'Piece', code: 'PCS', is_active: true }])

const POSITION = {
  sales_order_id: 5,
  sales_order_number: '2660001',
  sales_order_status: 'handed_off',
  customer_name: 'A Co',
  requested_delivery_date: '2026-10-05',
  can_create: true,
  scrap_allowance_percent: '2',
  allowance_locked: false,
  lines: [
    {
      sales_order_line_id: 1,
      product_id: 7,
      unit_of_measure_id: 2,
      ordered_quantity: '100',
      fulfilled_quantity: '40',
      remaining_quantity: '60',
      ceiling_quantity: '102',
      remaining_permitted_quantity: '62',
    },
  ],
}

const INSTRUCTION: DeliveryInstruction = {
  id: 11,
  delivery_number: '2680001',
  sales_order_id: 5,
  sales_order_number: '2660001',
  customer_id: 3,
  customer_name: 'A Co',
  status: 'pending',
  scrap_allowance_percent: '2',
  fulfilled_at: null,
  fulfilled_by_user_id: null,
  not_fulfilled_reason: null,
  not_fulfilled_at: null,
  created_by_user_id: 1,
  created_at: '2026-09-28T06:00:00',
  lines: [
    {
      id: 21,
      sales_order_line_id: 1,
      product_id: 7,
      unit_of_measure_id: 2,
      ordered_quantity: '100',
      quantity: '30',
      quantity_override_reason: null,
      pallet_count_default: null,
      pallet_count: 2,
      pallet_count_manual: true,
    },
  ],
}

let instruction = INSTRUCTION

beforeEach(() => {
  instruction = INSTRUCTION
  useAuthMock.mockReturnValue({ user: { role: 'manager' } })
  getMock.mockReset().mockImplementation((url: string) => {
    if (url === '/api/products') return Promise.resolve({ data: PRODUCTS })
    if (url === '/api/units-of-measure') return Promise.resolve({ data: UNITS })
    if (url === '/api/delivery-instructions/position') return Promise.resolve({ data: POSITION })
    if (url === '/api/delivery-instructions/11') return Promise.resolve({ data: instruction })
    if (url === '/api/delivery-instructions') return Promise.resolve({ data: page([instruction]) })
    if (url === '/api/delivery-instructions/eligible-orders') {
      return Promise.resolve({
        data: page([{ id: 5, order_number: '2660001', customer_name: 'A Co', requested_delivery_date: '2026-10-05', status: 'handed_off' }]),
      })
    }
    return Promise.reject(new Error(`unexpected ${url}`))
  })
  postMock.mockReset()
  patchMock.mockReset()
})

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/deliveries" element={<DeliveriesPage />} />
        <Route path="/deliveries/orders/:orderId" element={<DeliveryOrderPage />} />
        <Route path="/deliveries/:instructionId" element={<DeliveryInstructionPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Delivery pages', () => {
  it('lists eligible orders and instructions', async () => {
    renderAt('/deliveries')
    expect(await screen.findByRole('button', { name: 'Deliver' })).toBeInTheDocument()
    expect(await screen.findByText('2680001')).toBeInTheDocument()
  })

  it('shows access denied when the server refuses', async () => {
    getMock.mockImplementation(() => Promise.reject(new ApiError({ code: 'ACCESS_DENIED', message: 'No' }, 403)))
    renderAt('/deliveries')
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })

  it('shows the position and creates an instruction with only the entered shipment quantities', async () => {
    postMock.mockResolvedValue({ data: { ...INSTRUCTION, id: 11 } })
    renderAt('/deliveries/orders/5')
    expect(await screen.findByText('62')).toBeInTheDocument() // may still deliver
    await userEvent.click(screen.getByRole('button', { name: 'New Delivery Instruction' }))
    const create = screen.getByRole('button', { name: 'Create Delivery Instruction' })
    expect(create).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Ship now: Widget'), '25')
    await userEvent.click(create)
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))
    expect(postMock.mock.calls[0]).toEqual([
      '/api/delivery-instructions',
      { sales_order_id: 5, lines: [{ sales_order_line_id: 1, quantity: '25' }] },
    ])
  })

  it('does not offer creation when the server says the order cannot take one', async () => {
    getMock.mockImplementation((url: string) =>
      url === '/api/delivery-instructions/position'
        ? Promise.resolve({ data: { ...POSITION, can_create: false, sales_order_status: 'completed' } })
        : url === '/api/delivery-instructions'
          ? Promise.resolve({ data: page([]) })
          : Promise.resolve({ data: page([]) }),
    )
    renderAt('/deliveries/orders/5')
    expect(await screen.findByText(/cannot take a new delivery/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New Delivery Instruction' })).not.toBeInTheDocument()
  })

  it('confirms fulfilment with the shipment and position before posting', async () => {
    postMock.mockResolvedValue({ data: { ...INSTRUCTION, status: 'fulfilled' } })
    renderAt('/deliveries/11')
    await userEvent.click(await screen.findByRole('button', { name: 'Fulfil' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Widget: 30 PCS')).toBeInTheDocument()
    expect(within(dialog).getByText(/may still deliver 62/)).toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm Fulfilment' }))
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/delivery-instructions/11/fulfil'))
  })

  it('requires a reason to mark not fulfilled', async () => {
    postMock.mockResolvedValue({ data: INSTRUCTION })
    renderAt('/deliveries/11')
    await userEvent.click(await screen.findByRole('button', { name: 'Not Fulfilled' }))
    const confirm = screen.getByRole('button', { name: 'Confirm Not Fulfilled' })
    expect(confirm).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/reason/i), 'Road closed')
    await userEvent.click(confirm)
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/delivery-instructions/11/not-fulfilled', { reason: 'Road closed' }),
    )
  })

  it('sends only changed shipment fields and shows the server refusal', async () => {
    patchMock.mockRejectedValue(new ApiError({ code: 'CONFLICT', message: 'Only 62 may still be delivered.' }, 409))
    renderAt('/deliveries/11')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Shipment' }))
    const input = screen.getByLabelText('Ship quantity: Widget')
    await userEvent.clear(input)
    await userEvent.type(input, '70')
    expect(screen.queryByLabelText(/override reason/i)).not.toBeInTheDocument() // not an Admin
    await userEvent.click(screen.getByRole('button', { name: 'Save Shipment' }))
    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/api/delivery-instructions/11/lines/21', { quantity: '70' }))
    expect(await screen.findByText('Only 62 may still be delivered.')).toBeInTheDocument()
  })

  it('offers retry only for a not-fulfilled instruction and shows the reason', async () => {
    instruction = { ...INSTRUCTION, status: 'not_fulfilled', not_fulfilled_reason: 'No truck', not_fulfilled_at: '2026-09-28T07:00:00' }
    postMock.mockResolvedValue({ data: INSTRUCTION })
    renderAt('/deliveries/11')
    expect(await screen.findByText('Not fulfilled: No truck')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Fulfil' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry Delivery' }))
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/delivery-instructions/11/retry'))
  })

  it('downloads the latest Delivery Note through the files endpoint', async () => {
    instruction = { ...INSTRUCTION, pdf_file: { id: 99, original_filename: 'Delivery-Note-2680001.pdf' } }
    const createObjectURL = vi.fn(() => 'blob:x')
    const revokeObjectURL = vi.fn()
    Object.assign(window.URL, { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const base = getMock.getMockImplementation()!
    getMock.mockImplementation((url: string, config?: unknown) =>
      url === '/api/files/99' ? Promise.resolve({ data: new Blob(['%PDF']) }) : base(url, config),
    )
    renderAt('/deliveries/11')
    await userEvent.click(await screen.findByRole('button', { name: 'Delivery Note PDF' }))
    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(getMock).toHaveBeenCalledWith('/api/files/99', { responseType: 'blob' })
    click.mockRestore()
  })

  it('offers no Delivery Note download before one exists', async () => {
    renderAt('/deliveries/11')
    await screen.findByRole('button', { name: 'Fulfil' })
    expect(screen.queryByRole('button', { name: 'Delivery Note PDF' })).not.toBeInTheDocument()
  })
})
