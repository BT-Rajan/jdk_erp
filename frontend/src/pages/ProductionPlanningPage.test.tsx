import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/lib/apiClient'
import { ProductionPlanningPage, type MrpRow, type ProductionPlan } from './ProductionPlanningPage'

const { getMock, postMock, patchMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), patchMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock, patch: patchMock } }
})

const page = <T,>(data: T[]) => ({ data, pagination: { page: 1, page_size: 200, total: data.length, total_pages: 1 } })

const ROW: MrpRow = {
  demand_type: 'customer_demand',
  product_id: 7,
  product_name: 'Widget',
  unit_of_measure_id: 2,
  production_requirement_id: 3,
  requirement_status: 'open',
  sales_order_number: '2660001',
  line_number: 1,
  required_by_date: '2026-10-05',
  required_quantity: '1000',
  allocated_quantity: '600',
  outstanding_quantity: '400',
  fg_on_hand: '600',
  fg_allocated: '600',
  fg_free: '0',
  planned_quantity: '0',
  proposed_quantity: '400',
  excess_quantity: '0',
  plan_ids: [],
  plan_status: 'unplanned',
  bom_status: 'snapshot',
  materials: [
    {
      raw_material_id: 9,
      raw_material_name: 'Cement',
      unit_code: 'KG',
      required_quantity: '1200',
      on_hand_quantity: '1000',
      committed_quantity: '0',
      available_quantity: '1000',
      shortage_quantity: '200',
      unit_mismatch: false,
    },
  ],
  exceptions: ['material_shortage'],
}

const PLAN: ProductionPlan = {
  id: 11,
  product_id: 7,
  product_name: 'Widget',
  unit_of_measure_id: 2,
  planned_quantity: '300',
  original_quantity: '300',
  source_type: 'independent',
  production_requirement_id: null,
  sales_order_number: null,
  required_by_date: null,
  notes: null,
  status: 'draft',
  bom_id: 1,
  cancellation_reason: null,
}

beforeEach(() => {
  getMock.mockReset().mockImplementation((url: string) => {
    if (url === '/api/mrp') return Promise.resolve({ data: { rows: [ROW], material_summary: ROW.materials } })
    if (url === '/api/production-plans') return Promise.resolve({ data: [PLAN] })
    if (url === '/api/products') return Promise.resolve({ data: page([{ id: 7, name: 'Widget', code: 'W', is_active: true }]) })
    return Promise.resolve({ data: page([{ id: 2, name: 'Piece', code: 'PCS', is_active: true }]) })
  })
  postMock.mockReset().mockResolvedValue({ data: {} })
  patchMock.mockReset().mockResolvedValue({ data: {} })
})

const renderPage = () =>
  render(
    <MemoryRouter>
      <ProductionPlanningPage />
    </MemoryRouter>,
  )

describe('ProductionPlanningPage', () => {
  it('shows the demand, its exception and material shortage', async () => {
    renderPage()
    expect(await screen.findByText('2660001 / line 1')).toBeInTheDocument()
    expect(screen.getAllByText('Material short').length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Short' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Cement')).toBeInTheDocument()
    expect(within(dialog).getByText('1,200 KG')).toBeInTheDocument()
  })

  it('plans customer demand with the proposed quantity by default', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Plan' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Quantity to plan')).toHaveValue(400)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/production-plans', {
        source_type: 'customer_demand',
        production_requirement_id: 3,
        planned_quantity: '400',
        additional: false,
        notes: null,
      }),
    )
  })

  it('creates an independent plan with an explicit product and quantity', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'New Independent Plan' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(within(dialog).getByLabelText(/Product/), '7')
    await userEvent.type(within(dialog).getByLabelText(/Quantity/), '250')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/api/production-plans', {
        source_type: 'independent',
        product_id: 7,
        planned_quantity: '250',
        required_by_date: null,
        notes: null,
      }),
    )
  })

  it('cancelling a plan needs a reason', async () => {
    renderPage()
    await screen.findByText('#11')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: 'Cancel Plan' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Line down')
    await userEvent.click(confirm)
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/production-plans/11/cancel', { reason: 'Line down' }))
  })

  it('shows access denied without the production view permission', async () => {
    getMock.mockImplementation(() => Promise.reject(new ApiError({ code: 'ACCESS_DENIED', message: 'No' }, 403)))
    renderPage()
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })
})
