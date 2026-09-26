import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ApiError } from '@/lib/apiClient'
import { ProductionOrderDetailPage, ProductionOrdersPage, type ProductionOrder } from './ProductionOrdersPage'

const { getMock, postMock, patchMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), patchMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})

const ORDER: ProductionOrder = {
  id: 3,
  order_number: '2620001',
  status: 'draft',
  product_id: 7,
  product_name: 'Widget',
  unit_of_measure_id: 2,
  quantity: '400',
  machine_name: 'Machine 1',
  production_line_name: 'Line 1',
  scheduled_date: '2026-09-28',
  notes: null,
  bom_id: null,
  bom_base_quantity: null,
  components: [],
  production_plan_id: 11,
  plan_source_type: 'customer_demand',
  production_schedule_entry_id: 5,
  production_requirement_id: 4,
  sales_order_number: '2660001',
  sales_order_line_number: 1,
  required_by_date: '2026-10-05',
  created_at: '2026-09-26T06:00:00',
  issued_at: null,
  cancelled_at: null,
  cancellation_reason: null,
  history: [{ action: 'production_order_created', actor_user_id: 1, created_at: '2026-09-26T06:00:00', details: 'draft' }],
}

let order: ProductionOrder = ORDER

beforeEach(() => {
  order = ORDER
  getMock.mockReset().mockImplementation((url: string) => {
    if (url === '/api/production-orders') return Promise.resolve({ data: [ORDER] })
    if (url === '/api/production-orders/3') return Promise.resolve({ data: order })
    return Promise.resolve({ data: { data: [{ id: 2, name: 'Kilogram', code: 'KG', is_active: true }], pagination: {} } })
  })
  postMock.mockReset().mockResolvedValue({ data: {} })
  patchMock.mockReset().mockResolvedValue({ data: {} })
})

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/production/orders" element={<ProductionOrdersPage />} />
        <Route path="/production/orders/:orderId" element={<ProductionOrderDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('Production Orders', () => {
  it('lists orders with their source and status', async () => {
    renderAt('/production/orders')
    expect(await screen.findByText('2620001')).toBeInTheDocument()
    expect(screen.getByText('2660001 / line 1')).toBeInTheDocument()
    expect(screen.getAllByText('Draft').some((el) => el.closest('td'))).toBe(true)
  })

  it('issues a draft and shows the snapshot once issued', async () => {
    renderAt('/production/orders/3')
    await userEvent.click(await screen.findByRole('button', { name: 'Issue' }))
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/production-orders/3/issue'))
  })

  it('shows the issued BOM basis and offers no edit', async () => {
    order = {
      ...ORDER,
      status: 'issued',
      bom_id: 1,
      bom_base_quantity: '1',
      issued_at: '2026-09-26T07:00:00',
      components: [{ raw_material_id: 9, raw_material_name: 'Cement', quantity: '2', unit_of_measure_id: 2, required_quantity: '800' }],
    }
    renderAt('/production/orders/3')
    expect(await screen.findByText('Cement')).toBeInTheDocument()
    expect(screen.getByText('800 KG')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Issue' })).not.toBeInTheDocument()
  })

  it('cancelling needs a reason', async () => {
    renderAt('/production/orders/3')
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel Order' }))
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: 'Cancel Order' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Wrong quantity')
    await userEvent.click(confirm)
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/production-orders/3/cancel', { reason: 'Wrong quantity' }))
  })

  it('shows access denied without the production view permission', async () => {
    getMock.mockImplementation(() => Promise.reject(new ApiError({ code: 'ACCESS_DENIED', message: 'No' }, 403)))
    renderAt('/production/orders')
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })

  it('records production with only the quantity, and one reference per submission', async () => {
    order = { ...ORDER, status: 'issued', bom_id: 1, bom_base_quantity: '1000', produced_quantity: '0', remaining_quantity: '400' }
    postMock.mockRejectedValueOnce(new ApiError({ code: 'BUSINESS_RULE', message: 'Not enough raw material; nothing was posted.' }, 400))
    renderAt('/production/orders/3')
    await userEvent.click(await screen.findByRole('button', { name: 'Record Production' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Quantity produced/), '150')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Post Production' }))
    expect(await within(dialog).findByText('Not enough raw material; nothing was posted.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Post Production' }))
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(2))
    const [first, second] = postMock.mock.calls
    expect(first[0]).toBe('/api/production-orders/3/executions')
    expect(first[1]).toMatchObject({ produced_quantity: '150', executed_at: null, notes: null })
    // A retry of the same submission carries the same reference.
    expect(second[1].client_reference).toBe(first[1].client_reference)
    expect(first[1].client_reference).toBeTruthy()
  })

  it('shows produced / remaining and the execution history, and no cancel once produced', async () => {
    order = {
      ...ORDER,
      status: 'partially_completed',
      produced_quantity: '600',
      remaining_quantity: '400',
      executions: [{ id: 1, sequence: 1, produced_quantity: '600', unit_of_measure_id: 2, executed_at: '2026-09-28T06:00:00', notes: null, status: 'posted' }],
    }
    renderAt('/production/orders/3')
    expect(await screen.findByText('Posted')).toBeInTheDocument()
    expect(screen.getAllByText('600 KG').length).toBeGreaterThan(0)
    expect(screen.getAllByText('400 KG').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Cancel Order' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record Production' })).toBeInTheDocument()
  })

  it('opens Record Production directly from the daily screen shortcut', async () => {
    order = { ...ORDER, status: 'partially_completed', produced_quantity: '100', remaining_quantity: '300' }
    renderAt('/production/orders/3?record=1')
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText(/Quantity produced/)).toBeInTheDocument()
  })
})

