import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/lib/apiClient'
import { PlanScheduleDialog, ProductionSchedulePage, type PlanSchedule, type ScheduleDay, type ScheduleEntry } from './ProductionSchedulePage'

const { getMock, postMock, patchMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), patchMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})

const ENTRY: ScheduleEntry = {
  id: 5,
  production_plan_id: 11,
  machine_id: 1,
  scheduled_date: '2026-09-28',
  sequence: 1,
  product_id: 7,
  product_name: 'Widget',
  quantity: '550',
  unit_of_measure_id: 2,
  status: 'scheduled',
  source_type: 'customer_demand',
  sales_order_number: '2660001',
  required_by_date: '2026-09-27',
  late: true,
  cancellation_reason: null,
}

const DAY: ScheduleDay = {
  date: '2026-09-28',
  is_working_day: true,
  machines: [
    {
      machine_id: 1,
      machine_name: 'Machine 1',
      capacity_quantity: '500',
      capacity_unit_of_measure_id: 2,
      capacity_note: null,
      scheduled_load: '550',
      remaining_capacity: '0',
      overload_quantity: '50',
      entries: [ENTRY],
    },
  ],
}

const PLAN: PlanSchedule = {
  production_plan_id: 11,
  status: 'planned',
  unit_of_measure_id: 2,
  planned_quantity: '1000',
  scheduled_quantity: '750',
  unscheduled_quantity: '250',
  fully_scheduled: false,
  required_by_date: '2026-10-05',
  entries: [ENTRY],
  overloaded_dates: [],
  exceptions: ['not_fully_scheduled'],
}

beforeEach(() => {
  getMock.mockReset().mockImplementation((url: string) => {
    if (url === '/api/production-schedule/days') return Promise.resolve({ data: [DAY] })
    if (url === '/api/production-plans/11/schedule') return Promise.resolve({ data: PLAN })
    return Promise.resolve({ data: { data: [{ id: 2, name: 'Kilogram', code: 'KG', is_active: true }], pagination: {} } })
  })
  postMock.mockReset().mockResolvedValue({ data: {} })
  patchMock.mockReset().mockResolvedValue({ data: {} })
})

describe('ProductionSchedulePage', () => {
  it('shows the day with capacity, overload and late entries, and moves between days', async () => {
    render(<MemoryRouter><ProductionSchedulePage /></MemoryRouter>)
    expect(await screen.findByText('Machine 1')).toBeInTheDocument()
    expect(screen.getByText('Overloaded by 50 KG')).toBeInTheDocument()
    expect(screen.getByText('Late')).toBeInTheDocument()
    expect(screen.getByText('2660001')).toBeInTheDocument()
    const calls = getMock.mock.calls.filter(([url]) => url === '/api/production-schedule/days').length
    await userEvent.click(screen.getByRole('button', { name: 'Next day' }))
    await waitFor(() => expect(getMock.mock.calls.filter(([url]) => url === '/api/production-schedule/days').length).toBe(calls + 1))
  })

  it('moves an entry with only what changed and a reason', async () => {
    render(<MemoryRouter><ProductionSchedulePage /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Move' }))
    const dialog = await screen.findByRole('dialog')
    const date = within(dialog).getByLabelText('Production date')
    await userEvent.clear(date)
    await userEvent.type(date, '2026-09-29')
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Maintenance')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith('/api/production-schedule/5', { reason: 'Maintenance', scheduled_date: '2026-09-29' }),
    )
  })

  it('shows access denied without the production view permission', async () => {
    getMock.mockImplementation(() => Promise.reject(new ApiError({ code: 'ACCESS_DENIED', message: 'No' }, 403)))
    render(<MemoryRouter><ProductionSchedulePage /></MemoryRouter>)
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })
})

describe('PlanScheduleDialog', () => {
  it('shows planned / scheduled / unscheduled and schedules the rest', async () => {
    render(<PlanScheduleDialog planId={11} onClose={() => undefined} />)
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('250 KG')).toBeInTheDocument()
    expect(within(dialog).getByText('Not fully scheduled')).toBeInTheDocument()
    const date = within(dialog).getAllByLabelText('Production date')[0]
    await userEvent.type(date, '2026-09-29')
    await userEvent.type(within(dialog).getByLabelText('Quantity'), '250')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Schedule' }))
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/production-schedule', { production_plan_id: 11, scheduled_date: '2026-09-29', quantity: '250' }),
    )
  })
})
