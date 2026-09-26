import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { ApiError } from '@/lib/apiClient'
import { ProductionTodayPage, type DayStatus } from './ProductionTodayPage'

const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock } }
})

const DAY: DayStatus = {
  date: '2026-09-28',
  is_working_day: true,
  previous_working_day: '2026-09-27',
  next_working_day: '2026-09-29',
  order_count: 2,
  completed_count: 0,
  in_progress_count: 1,
  not_started_count: 1,
  cancelled_count: 0,
  totals: [{ unit_of_measure_id: 2, scheduled_quantity: '1900', produced_quantity: '600', remaining_quantity: '1300' }],
  orders: [
    {
      production_order_id: 3,
      order_number: '2620001',
      sequence: 1,
      product_id: 7,
      product_name: 'Widget',
      unit_of_measure_id: 2,
      planned_quantity: '1000',
      produced_quantity: '600',
      remaining_quantity: '400',
      status: 'partially_completed',
      scheduled_date: '2026-09-28',
      required_by_date: null,
      production_line_name: 'Line 1',
      source_type: 'independent',
      sales_order_number: null,
      sales_order_line_number: null,
      exceptions: ['material_shortage'],
    },
    {
      production_order_id: 4,
      order_number: '2620002',
      sequence: 2,
      product_id: 7,
      product_name: 'Widget',
      unit_of_measure_id: 2,
      planned_quantity: '900',
      produced_quantity: '0',
      remaining_quantity: '900',
      status: 'completed',
      scheduled_date: '2026-09-28',
      required_by_date: '2026-10-05',
      production_line_name: 'Line 1',
      source_type: 'customer_demand',
      sales_order_number: '2660001',
      sales_order_line_number: 1,
      exceptions: [],
    },
  ],
}

function Where() {
  const location = useLocation()
  return <div data-testid="where">{location.pathname + location.search}</div>
}

beforeEach(() => {
  getMock.mockReset().mockImplementation((url: string) =>
    url === '/api/production-status/day'
      ? Promise.resolve({ data: DAY })
      : Promise.resolve({ data: { data: [{ id: 2, name: 'Kilogram', code: 'KG', is_active: true }], pagination: {} } }),
  )
})

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/production/today']}>
      <Routes>
        <Route path="/production/today" element={<ProductionTodayPage />} />
        <Route path="/production/orders/:orderId" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )

describe('ProductionTodayPage', () => {
  it('shows the day with totals, statuses and exceptions', async () => {
    renderPage()
    expect(await screen.findByText('2620001')).toBeInTheDocument()
    expect(screen.getByText('1,900 KG')).toBeInTheDocument()
    expect(screen.getByText('1,300 KG')).toBeInTheDocument()
    expect(screen.getByText('Partially completed')).toBeInTheDocument()
    expect(screen.getByText('Material short')).toBeInTheDocument()
    expect(screen.getByText('2660001 / line 1')).toBeInTheDocument()
  })

  it('moves to the previous and next working day from the server', async () => {
    renderPage()
    await screen.findByText('2620001')
    await userEvent.click(screen.getByRole('button', { name: 'Next working day' }))
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/api/production-status/day', { params: { date: '2026-09-29' } }))
    await userEvent.click(screen.getByRole('button', { name: 'Previous working day' }))
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/api/production-status/day', { params: { date: '2026-09-27' } }))
  })

  it('offers Record Production only for executable orders and opens it on the order', async () => {
    renderPage()
    await screen.findByText('2620001')
    const buttons = screen.getAllByRole('button', { name: 'Record Production' })
    expect(buttons).toHaveLength(1) // the completed order has none
    await userEvent.click(buttons[0])
    expect(await screen.findByTestId('where')).toHaveTextContent('/production/orders/3?record=1')
  })

  it('shows access denied without production permission', async () => {
    getMock.mockImplementation(() => Promise.reject(new ApiError({ code: 'ACCESS_DENIED', message: 'No' }, 403)))
    renderPage()
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })
})
