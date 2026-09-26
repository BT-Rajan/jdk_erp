import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ApiError } from '@/lib/apiClient'
import { ProductionRequirementsPage, type ProductionRequirementRow } from './ProductionRequirementsPage'

const { getMock, postMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn() }))

vi.mock('@/lib/apiClient', async () => {
  const actual = await vi.importActual<typeof import('@/lib/apiClient')>('@/lib/apiClient')
  return { ...actual, apiClient: { get: getMock, post: postMock } }
})

const page = <T,>(data: T[]) => ({ data, pagination: { page: 1, page_size: 20, total: data.length, total_pages: 1 } })

const ROW: ProductionRequirementRow = {
  id: 3,
  sales_order_id: 5,
  sales_order_number: '2660001',
  sales_order_status: 'handed_off',
  customer_name: 'A Co',
  line_number: 1,
  product_id: 7,
  product_name: 'Gadget',
  unit_of_measure_id: 2,
  ordered_quantity: '25',
  covered_quantity: '10',
  quantity: '15',
  delivered_quantity: '0',
  required_quantity: '25',
  allocated_quantity: '10',
  outstanding_quantity: '15',
  required_by_date: '2026-10-05',
  status: 'bom_required',
  bom_id: null,
  cancellation_reason: null,
  can_resolve_bom: true,
}

beforeEach(() => {
  getMock.mockReset().mockImplementation((url: string) =>
    Promise.resolve({ data: url === '/api/units-of-measure' ? page([{ id: 2, name: 'Piece', code: 'PCS', is_active: true }]) : page([ROW]) }),
  )
  postMock.mockReset().mockResolvedValue({ data: { ...ROW, status: 'open' } })
})

const renderPage = () =>
  render(
    <MemoryRouter>
      <ProductionRequirementsPage />
    </MemoryRouter>,
  )

describe('ProductionRequirementsPage', () => {
  it('lists the demand and takes a BOM snapshot only when the server allows it', async () => {
    renderPage()
    expect(await screen.findByText('2660001 / line 1')).toBeInTheDocument()
    expect(screen.getAllByText('BOM required').some((el) => el.closest('td'))).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Take BOM Snapshot' }))
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/api/production-requirements/3/snapshot-bom'))
  })

  it('offers no action without the manage permission', async () => {
    getMock.mockImplementation((url: string) =>
      Promise.resolve({ data: url === '/api/units-of-measure' ? page([]) : page([{ ...ROW, can_resolve_bom: false }]) }),
    )
    renderPage()
    await screen.findByText('2660001 / line 1')
    expect(screen.queryByRole('button', { name: 'Take BOM Snapshot' })).not.toBeInTheDocument()
  })

  it('filters by status on the server', async () => {
    renderPage()
    await screen.findByText('2660001 / line 1')
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'cancelled')
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith('/api/production-requirements', expect.objectContaining({ params: expect.objectContaining({ status: 'cancelled' }) })),
    )
  })

  it('shows access denied without the view permission', async () => {
    getMock.mockImplementation(() => Promise.reject(new ApiError({ code: 'ACCESS_DENIED', message: 'No' }, 403)))
    renderPage()
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })
})
